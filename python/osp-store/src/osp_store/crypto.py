"""Application-level field encryption (AES-256-GCM) with key rotation.

Ciphertext layout: ``b"\\x01" + nonce(12) + ciphertext||tag(16)``. The key id is
stored in a sibling column per row, so several keys can be live during a rotation.

The associated data binds a ciphertext to its table, column and row id, so a blob
copied into another row (or another tenant's row) fails to decrypt.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import CryptoError

_FORMAT = b"\x01"
_NONCE = 12

ENV_KEYS = "OSP_STORE_KEYS"
ENV_ACTIVE = "OSP_STORE_ACTIVE_KEY"


def generate_key() -> str:
    """A fresh 256-bit key, base64 (urlsafe) encoded, for config files."""
    return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")


def _decode_key(key_id: str, value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        raw = value
    else:
        try:
            raw = base64.urlsafe_b64decode(value.encode("ascii"))
        except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
            raise CryptoError(f"key {key_id!r} is not valid base64") from exc
    if len(raw) != 32:
        raise CryptoError(f"key {key_id!r} must be 32 bytes (AES-256), got {len(raw)}")
    return raw


@dataclass(frozen=True)
class Encrypted:
    key_id: str
    blob: bytes


class Keyring:
    """Named AES-256 keys; new data is written with ``active``."""

    def __init__(self, keys: Mapping[str, str | bytes], active: str) -> None:
        if not keys:
            raise CryptoError("keyring is empty")
        if active not in keys:
            raise CryptoError(f"active key {active!r} is not in the keyring")
        for kid in keys:
            if not isinstance(kid, str) or not kid or len(kid) > 32 or ":" in kid or "," in kid:
                raise CryptoError(f"bad key id {kid!r}")
        self._keys = {kid: AESGCM(_decode_key(kid, v)) for kid, v in keys.items()}
        self.active = active

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Keyring:
        """``OSP_STORE_KEYS="k1:<b64>,k2:<b64>"`` and ``OSP_STORE_ACTIVE_KEY="k2"``."""
        env = os.environ if environ is None else environ
        spec = env.get(ENV_KEYS, "")
        keys: dict[str, str] = {}
        for part in filter(None, (p.strip() for p in spec.split(","))):
            kid, sep, value = part.partition(":")
            if not sep:
                raise CryptoError(f"{ENV_KEYS} entries must be '<id>:<base64>'")
            keys[kid] = value
        active = env.get(ENV_ACTIVE) or (next(reversed(keys)) if keys else "")
        return cls(keys, active)

    @property
    def key_ids(self) -> frozenset[str]:
        return frozenset(self._keys)

    def encrypt(self, plaintext: bytes, aad: bytes) -> Encrypted:
        nonce = os.urandom(_NONCE)
        ct = self._keys[self.active].encrypt(nonce, plaintext, aad)
        return Encrypted(self.active, _FORMAT + nonce + ct)

    def decrypt(self, key_id: str, blob: bytes, aad: bytes) -> bytes:
        aes = self._keys.get(key_id)
        if aes is None:
            raise CryptoError(f"unknown key id {key_id!r}")
        blob = bytes(blob)
        if len(blob) < 1 + _NONCE + 16 or blob[:1] != _FORMAT:
            raise CryptoError("malformed ciphertext")
        try:
            return aes.decrypt(blob[1 : 1 + _NONCE], blob[1 + _NONCE :], aad)
        except InvalidTag as exc:
            raise CryptoError("decryption failed (wrong key, wrong row, or tampered)") from exc

    # JSON helpers: the encrypted fields are all JSON values.
    def encrypt_json(self, value: object, aad: bytes) -> Encrypted:
        return self.encrypt(canonical_json(value).encode("utf-8"), aad)

    def decrypt_json(self, key_id: str, blob: bytes, aad: bytes) -> object:
        return json.loads(self.decrypt(key_id, blob, aad))


def aad_for(table: str, column: str, row_id: str) -> bytes:
    return f"osp-store/{table}.{column}/{row_id}".encode()


def canonical_json(value: object) -> str:
    """Sorted keys, no whitespace, UTF-8, no NaN. The input to every checksum."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
