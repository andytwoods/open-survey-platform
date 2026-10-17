"""Wiring: the builder and participant sessions over osp-store, plus admitting identities.

Researchers are the host's (plan P). :meth:`AppServices.admit` runs once per builder
request with what the host vouched for: it records the principal (display name, last
seen) for audit display and makes sure the actor's labs exist (D6).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from osp_runtime import SessionService
from osp_store import Store, SystemContext

from .auth import Actor
from .auth.ports import Clock
from .builder import Builder
from .identity import Identity
from .osf import Transport
from .runtime_repo import StoreParticipantRepo

SYS = SystemContext("system:identity")
TOUCH_EVERY_S = 60.0  # refresh a principal's last-seen at most this often (same name)


@dataclass
class AppServices:
    store: Store
    builder: Builder
    sessions: SessionService  # participant sessions; publish registers plans here
    auto_create_labs: bool = True  # OSP_AUTO_CREATE_LABS (D6)
    # How the OSF upload (osp_app.prereg) reaches the network; None: urllib. Tests set a fake.
    osf_transport: Transport | None = None
    _labs: set[str] = field(default_factory=set, repr=False)
    _touched: dict[str, tuple[str | None, float]] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def admit(self, identity: Identity) -> Actor:
        """The actor a builder request runs as.

        - Upserts the ``principals`` row (throttled: once a minute unless the name changed),
          so audit rows written by this request carry the current display name.
        - Each lab the host names is created on first sight when ``auto_create_labs`` is on;
          when it is off, a lab nobody created (``osp-cli lab create``) confers nothing and
          is dropped from the actor. Roles always come from the host, never from storage.
        """
        actor = identity.actor
        self._touch(actor.user_id, identity.display_name)
        roles = {tid: role for tid, role in actor.roles.items() if self._lab_ok(tid)}
        return actor if len(roles) == len(actor.roles) else Actor(actor.user_id, roles)

    def display_name(self, user_id: str) -> str | None:
        p = self.store.get_principal(SYS, user_id)
        return None if p is None else p.display_name

    def create_lab(self, tenant_id: str, name: str | None = None) -> str:
        """Create a lab with the host's id (CLI / bootstrap use, or JIT). Returns the id."""
        lab = self.store.ensure_tenant(SYS, tenant_id, name)
        with self._lock:
            self._labs.add(lab.id)
        return lab.id

    def _lab_ok(self, tenant_id: str) -> bool:
        if tenant_id in self._labs:
            return True
        if self.auto_create_labs:
            self.create_lab(tenant_id)
            return True
        if self.store.find_tenant(SYS, tenant_id) is None:
            return False
        with self._lock:
            self._labs.add(tenant_id)
        return True

    def _touch(self, user_id: str, name: str | None) -> None:
        now = time.monotonic()
        with self._lock:
            seen = self._touched.get(user_id)
        if seen is not None and (name is None or seen[0] == name) and now - seen[1] < TOUCH_EVERY_S:
            return
        stored = self.store.touch_principal(SYS, user_id, name)
        with self._lock:
            self._touched[user_id] = (stored.display_name, now)


def build_services(
    store: Store,
    *,
    clock: Clock | None = None,
    auto_create_labs: bool = True,
    media_origins: Sequence[str] | None = None,
) -> AppServices:
    """``media_origins`` (planning/media.md §2.3, ``OSP_MEDIA_ORIGINS``): the origins media
    URLs may use besides the page's own; None leaves the check off."""
    sessions = SessionService(
        StoreParticipantRepo(store), **({"clock": clock.now} if clock is not None else {})
    )
    return AppServices(
        store=store,
        builder=Builder(store, sessions, media_origins=media_origins),
        sessions=sessions,
        auto_create_labs=auto_create_labs,
    )
