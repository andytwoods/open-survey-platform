"""Typed store errors. Callers map these to diagnostics / HTTP codes; nothing else escapes."""

from __future__ import annotations


class StoreError(Exception):
    """Base class for every error the store raises on purpose."""


class AccessDenied(StoreError):
    """No (or a malformed) tenant context. The store fails closed."""


class NotFound(StoreError):
    """The row does not exist *in the caller's tenant*.

    A row that exists in another tenant is reported exactly like a missing one,
    so callers cannot probe for other tenants' ids.
    """


class RevisionConflict(StoreError):
    """Optimistic concurrency: the caller's base revision is stale."""

    def __init__(self, expected: int, current: int) -> None:
        super().__init__(f"stale revision: based on {expected}, current is {current}")
        self.expected = expected
        self.current = current


class InvalidInput(StoreError):
    """Input the store refuses to persist (not JSON, bad enum, bad seed, ...)."""


class Conflict(StoreError):
    """A uniqueness rule was violated (duplicate email, ...)."""


class CryptoError(StoreError):
    """Decryption failed: unknown key id, wrong key, or tampered ciphertext."""
