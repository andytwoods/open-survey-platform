"""Server-side sessions with opaque tokens.

The client holds a random token (256 bits, URL-safe base64). The server stores
only SHA-256(token) as the session id, so a leaked session table can't be
replayed. Sessions have an idle timeout and an absolute lifetime. `rotate`
issues a fresh token for the same session state (call it whenever the
session's privilege changes, e.g. MFA completion or TOTP enrolment).
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, replace
from datetime import timedelta

from .model import Session, SessionStage
from .ports import Clock, RandomSource
from .repos import SessionRepo

TOKEN_BYTES = 32


@dataclass(frozen=True)
class SessionConfig:
    idle_timeout: timedelta = timedelta(minutes=30)
    absolute_lifetime: timedelta = timedelta(hours=12)
    mfa_pending_lifetime: timedelta = timedelta(minutes=5)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionManager:
    def __init__(
        self,
        repo: SessionRepo,
        clock: Clock,
        rng: RandomSource,
        config: SessionConfig | None = None,
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._rng = rng
        self.config = config or SessionConfig()

    def _new_token(self) -> str:
        return base64.urlsafe_b64encode(self._rng.token_bytes(TOKEN_BYTES)).decode().rstrip("=")

    def create(self, user_id: str, stage: SessionStage = SessionStage.FULL) -> str:
        now = self._clock.now()
        life = (
            self.config.absolute_lifetime
            if stage is SessionStage.FULL
            else self.config.mfa_pending_lifetime
        )
        token = self._new_token()
        self._repo.add(
            Session(
                id=hash_token(token),
                user_id=user_id,
                stage=stage,
                created_at=now,
                last_seen_at=now,
                expires_at=now + life,
            )
        )
        return token

    def _live(self, token: object, stage: SessionStage) -> Session | None:
        if not isinstance(token, str) or not token or len(token) > 256:
            return None
        session = self._repo.get(hash_token(token))
        if session is None or session.stage is not stage:
            return None
        now = self._clock.now()
        if now >= session.expires_at or now - session.last_seen_at >= self.config.idle_timeout:
            self._repo.delete(session.id)
            return None
        return session

    def authenticate(self, token: object) -> Session | None:
        """The live, fully authenticated session for `token`, touching its idle timer."""
        session = self._live(token, SessionStage.FULL)
        if session is None:
            return None
        session = replace(session, last_seen_at=self._clock.now())
        self._repo.update(session)
        return session

    def peek_pending(self, token: object) -> Session | None:
        """The live MFA-pending session for `token` (does not touch it)."""
        return self._live(token, SessionStage.MFA_PENDING)

    def rotate(self, token: object) -> str | None:
        """Replace a live full session's token; the old token stops working.
        Keeps the original absolute expiry."""
        session = self._live(token, SessionStage.FULL)
        if session is None:
            return None
        self._repo.delete(session.id)
        new_token = self._new_token()
        self._repo.add(replace(session, id=hash_token(new_token), last_seen_at=self._clock.now()))
        return new_token

    def revoke(self, token: object) -> None:
        if isinstance(token, str) and token:
            self._repo.delete(hash_token(token))

    def revoke_all(self, user_id: str) -> None:
        self._repo.delete_for_user(user_id)

    def revoke_all_except(self, user_id: str, keep_token: str) -> None:
        keep = hash_token(keep_token)
        for session in self._repo.list_for_user(user_id):
            if session.id != keep:
                self._repo.delete(session.id)
