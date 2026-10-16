"""TOTP (RFC 6238 over RFC 4226 HOTP) and one-time recovery codes.

A small own implementation instead of a dependency: HMAC-SHA1, 6 digits,
30-second steps, which is what authenticator apps expect by default. Checked
against the RFC 6238 appendix B test vectors.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
from datetime import datetime
from urllib.parse import quote, urlencode

from .ports import RandomSource

DIGITS = 6
PERIOD = 30
WINDOW = 1  # accept the previous, current and next step (clock drift)
SECRET_BYTES = 20  # 160 bits, RFC 4226 recommendation
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_BYTES = 10  # 80 bits -> 16 base32 characters
_B32_ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def generate_secret(rng: RandomSource) -> str:
    return base64.b32encode(rng.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _key(secret_b32: str) -> bytes:
    s = secret_b32.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def hotp(key: bytes, counter: int, *, digits: int = DIGITS, digest: str = "sha1") -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), digest).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**digits
    return str(code).zfill(digits)


def time_step(at: datetime) -> int:
    return int(at.timestamp()) // PERIOD


def totp(secret_b32: str, at: datetime) -> str:
    return hotp(_key(secret_b32), time_step(at))


def verify(secret_b32: str, code: object, at: datetime, *, last_step: int | None) -> int | None:
    """Return the matched time step, or None.

    Accepts steps within ±WINDOW of `at`, but never a step at or before
    `last_step`: a code (or an older one) can be used only once.
    """
    if not isinstance(code, str):
        return None
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isascii() or not code.isdigit():
        return None
    try:
        key = _key(secret_b32)
    except ValueError:
        return None
    now = time_step(at)
    matched: int | None = None
    for step in range(now - WINDOW, now + WINDOW + 1):
        # Compare every candidate so timing doesn't reveal which step matched.
        if hmac.compare_digest(hotp(key, step), code) and matched is None:
            matched = step
    if matched is None or (last_step is not None and matched <= last_step):
        return None
    return matched


def provisioning_uri(secret_b32: str, account: str, issuer: str) -> str:
    """otpauth:// URI (Google Authenticator key URI format) for a QR code."""
    label = quote(f"{issuer}:{account}", safe="@:")
    query = urlencode(
        {
            "secret": secret_b32,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": PERIOD,
        },
        quote_via=quote,
    )
    return f"otpauth://totp/{label}?{query}"


# --- recovery codes ---------------------------------------------------------


def _canonical_recovery(code: str) -> str:
    return code.strip().replace("-", "").replace(" ", "").upper()


def hash_recovery_code(code: str) -> str:
    """SHA-256 is enough here: codes carry 80 bits of entropy (unlike passwords)."""
    return hashlib.sha256(_canonical_recovery(code).encode("ascii")).hexdigest()


def generate_recovery_codes(rng: RandomSource) -> list[str]:
    """Plain codes to show the user once, formatted XXXX-XXXX-XXXX-XXXX."""
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = base64.b32encode(rng.token_bytes(RECOVERY_CODE_BYTES)).decode("ascii")
        codes.append("-".join(raw[i : i + 4] for i in range(0, 16, 4)))
    return codes


def match_recovery_code(code: object, hashes: tuple[str, ...]) -> str | None:
    """Return the stored hash that `code` matches (to remove it), or None."""
    if not isinstance(code, str):
        return None
    canon = _canonical_recovery(code)
    if len(canon) != 16 or not set(canon) <= _B32_ALPHABET:
        return None
    candidate = hash_recovery_code(canon)
    found = None
    for h in hashes:
        if hmac.compare_digest(h, candidate):
            found = h
    return found
