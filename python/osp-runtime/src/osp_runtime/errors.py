"""Typed session errors. ``osp-api`` maps each class to one HTTP status; ``code`` is a
stable diagnostic id for the client."""

from __future__ import annotations

from typing import Any


class SessionError(Exception):
    code = "session.error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class NotFoundError(SessionError):
    """No such survey link, plan, or quota node (404)."""

    code = "not_found"


class SurveyClosed(SessionError):
    """The publication is closed to new sessions (410)."""

    code = "survey.closed"


class InvalidToken(SessionError):
    """Missing or wrong resume token, or a token for another session (401)."""

    code = "token.invalid"


class SessionExpired(SessionError):
    """The resume token was idle past its resume expiry (30 days by default) and no
    longer works for snapshots, quota checks or resume (410). Submit still accepts it
    and flags the response ``late`` (decision S-2)."""

    code = "session.expired"


class SessionSubmitted(SessionError):
    """The session was submitted; no further snapshots or quota checks (409)."""

    code = "session.submitted"


class SaveModeForbidden(SessionError):
    """``end-only`` surveys accept no response data before submit (403)."""

    code = "save_mode.end_only"


class StaleRevision(SessionError):
    """Conditional write lost: ``baseRevision`` is not the current revision (409)."""

    code = "snapshot.stale"

    def __init__(self, revision: int, snapshot: Any) -> None:
        super().__init__(f"stale baseRevision; the server is at revision {revision}")
        self.revision = revision
        self.snapshot = snapshot


class SubmitMismatch(SessionError):
    """A second submit with a different payload (409)."""

    code = "submit.mismatch"


class InvalidPayload(SessionError):
    """Bad request body: shape, plan checksum, assignment (422)."""

    code = "payload.invalid"


class PayloadTooLarge(SessionError):
    code = "payload.too_large"  # 413


class RateLimited(SessionError):
    code = "rate_limited"  # 429
