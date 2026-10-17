"""A replay ledger for one-time nonces, shared through the database (D16).

osp-api's TrustedHeaders provider remembers each signed request's ``X-OSP-Nonce`` until
its timestamp is too old to be accepted. With several workers (or machines) an in-memory
cache only covers one of them; this table covers every worker on the same database.

:meth:`NonceLedger.claim` is insert-if-absent in one transaction: an expired row for the
same nonce is deleted first, then ``INSERT ... ON CONFLICT DO NOTHING``, so exactly one of
several concurrent claims wins. Expired rows are purged at most every ``purge_every``
seconds (by whichever claim comes along) and by :meth:`purge`.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, delete, func, insert, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError

from . import schema as t
from .errors import InvalidInput

MAX_NONCE = 64
PURGE_EVERY_S = 60.0
_T = t.identity_nonces


class NonceLedger:
    def __init__(self, engine: Engine, *, purge_every: float = PURGE_EVERY_S) -> None:
        self._engine = engine
        self._purge_every = timedelta(seconds=purge_every)
        self._next_purge: datetime | None = None
        self._lock = threading.Lock()

    def _insert(self, nonce: str, expires: datetime) -> Any:
        values = {"nonce": nonce, "expires_at": expires}
        name = self._engine.dialect.name
        if name == "postgresql":
            return postgresql.insert(_T).values(**values).on_conflict_do_nothing()
        if name == "sqlite":
            return sqlite.insert(_T).values(**values).on_conflict_do_nothing()
        return insert(_T).values(**values)  # elsewhere a conflict raises instead

    def claim(self, nonce: str, now: datetime, ttl: timedelta) -> bool:
        """True if ``nonce`` was not live (it is now held until ``now + ttl``); False if it
        was claimed before and has not expired: a replay."""
        if not isinstance(nonce, str) or not 0 < len(nonce) <= MAX_NONCE:
            raise InvalidInput("nonce must be 1-64 characters")
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise InvalidInput("now must be a timezone-aware datetime")
        self._maybe_purge(now)
        try:
            with self._engine.begin() as conn:
                conn.execute(delete(_T).where(_T.c.nonce == nonce, _T.c.expires_at <= now))
                return conn.execute(self._insert(nonce, now + ttl)).rowcount == 1
        except IntegrityError:
            return False

    def purge(self, now: datetime) -> int:
        """Delete every expired nonce; returns how many."""
        with self._engine.begin() as conn:
            return conn.execute(delete(_T).where(_T.c.expires_at <= now)).rowcount

    def count(self) -> int:
        with self._engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(_T)).scalar_one()

    def _maybe_purge(self, now: datetime) -> None:
        with self._lock:
            due = self._next_purge is None or now >= self._next_purge
            if due:
                self._next_purge = now + self._purge_every
        if due:
            self.purge(now)
