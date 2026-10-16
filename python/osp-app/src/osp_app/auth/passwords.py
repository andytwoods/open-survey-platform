"""Password policy (NIST SP 800-63B style) and argon2id hashing.

Policy: a minimum length, a maximum length (DoS guard, well above the 64 NIST
asks us to accept), a blocklist of common/breached passwords, context words
(the user's email, the service name) and trivially repetitive strings. No
composition rules ("one digit, one symbol") and no forced periodic changes.
Unicode is NFKC-normalised before checking and hashing; spaces are allowed.
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from importlib import resources

from argon2 import PasswordHasher as _Argon2
from argon2 import Type
from argon2.exceptions import InvalidHashError, VerificationError

# The deployment decides the password rule (user decision, 16 Oct 2026): set
# OSP_PASSWORD_MIN_LENGTH, or use institutional SSO. The default is the NIST
# SP 800-63B baseline of 8, alongside the breached/common-password blocklist.
DEFAULT_MIN_LENGTH = 8
MIN_LENGTH_ENV = "OSP_PASSWORD_MIN_LENGTH"
DEFAULT_MAX_LENGTH = 256
SERVICE_WORDS = ("opensurvey", "open survey", "osp")


@cache
def _blocklist() -> frozenset[str]:
    text = resources.files(__package__).joinpath("common_passwords.txt").read_text("utf-8")
    return frozenset(
        line.strip().lower() for line in text.splitlines() if line.strip() and line[0] != "#"
    )


def normalise_password(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def _is_repetitive(pw: str) -> bool:
    """True for strings made of one short unit repeated ("aaaa…", "abcabc…")."""
    n = len(pw)
    return any(n % k == 0 and pw == pw[:k] * (n // k) for k in range(1, min(4, n // 2) + 1))


def _is_sequential(pw: str) -> bool:
    """True for runs like "abcdef…" or "987654…" (constant code-point step of ±1)."""
    if len(pw) < 4:
        return False
    steps = {ord(b) - ord(a) for a, b in zip(pw, pw[1:], strict=False)}
    return steps in ({1}, {-1})


@dataclass(frozen=True)
class PasswordPolicy:
    min_length: int = DEFAULT_MIN_LENGTH
    max_length: int = DEFAULT_MAX_LENGTH
    context_words: tuple[str, ...] = field(default=SERVICE_WORDS)

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> PasswordPolicy:
        """The deployment policy: OSP_PASSWORD_MIN_LENGTH if valid, else the default."""
        raw = (os.environ if environ is None else environ).get(MIN_LENGTH_ENV, "").strip()
        if raw.isdigit() and 1 <= int(raw) <= DEFAULT_MAX_LENGTH:
            return cls(min_length=int(raw))
        return cls()

    def problems(self, password: object, *, email: str | None = None) -> list[str]:
        """Human-readable reasons the password is rejected; empty means OK."""
        if not isinstance(password, str):
            return ["Password must be text."]
        pw = normalise_password(password)
        length = len(pw)
        if length < self.min_length:
            return [f"Use at least {self.min_length} characters."]
        if length > self.max_length:
            return [f"Use at most {self.max_length} characters."]
        low = pw.lower()
        out: list[str] = []
        if low in _blocklist() or low.strip() in _blocklist():
            out.append("This password is too common. Choose something less guessable.")
        if _is_repetitive(low) or _is_sequential(low):
            out.append("Avoid repeated or sequential characters.")
        words = list(self.context_words)
        if email:
            local = email.strip().lower().split("@", 1)[0]
            words += [email.strip().lower()] + ([local] if len(local) >= 4 else [])
        if any(w and w in low for w in words):
            out.append("Don't include your email address or the service name.")
        return out


class PasswordHasher:
    """argon2id via argon2-cffi. Defaults are argon2-cffi's (RFC 9106 low-memory
    profile: t=3, m=64 MiB, p=4). Tests pass cheaper parameters."""

    def __init__(self, *, time_cost: int = 3, memory_cost: int = 65536, parallelism: int = 4):
        self._h = _Argon2(
            time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism, type=Type.ID
        )

    def hash(self, password: str) -> str:
        return self._h.hash(normalise_password(password))

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._h.verify(password_hash, normalise_password(password))
        except VerificationError, InvalidHashError:
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._h.check_needs_rehash(password_hash)
        except InvalidHashError, ValueError:
            return True
