"""Application errors. L6 shells map each to one HTTP status; nothing else escapes.

Messages are safe to show: they never reveal whether a resource exists in another
tenant (that is always plain `NotFoundError`).
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "app.error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Unauthenticated(AppError):
    code = "auth.required"


class Forbidden(AppError):
    code = "auth.forbidden"


class NotFoundError(AppError):
    code = "not_found"


class InvalidRequest(AppError):
    code = "request.invalid"


class ConflictError(AppError):
    code = "conflict"


class RevisionConflictError(AppError):
    """Stale ``baseRevision``: refetch and replay (builder-design §4)."""

    code = "op.conflict"

    def __init__(self, base_revision: object, current_revision: int) -> None:
        super().__init__(
            f"base revision {str(base_revision)[:20]} is stale; current is {current_revision}"
        )
        self.current_revision = current_revision


class UpstreamError(AppError):
    """An outside service (OSF) refused or could not be reached. The message never
    carries a credential."""

    code = "upstream"


class Rejected(AppError):
    """The edit, publish or export was refused; ``diagnostics`` say why."""

    code = "rejected"

    def __init__(
        self, message: str, diagnostics: list[Any], failed_index: int | None = None
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics
        self.failed_index = failed_index
