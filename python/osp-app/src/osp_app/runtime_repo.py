"""Adapter: ``osp_store.ParticipantStore`` as ``osp_runtime.ParticipantRepo``.

The two packages share layer L4, so they cannot import each other; this L5 shim binds
the store's typed contexts (``Builder.publish`` and the participant API share it). Every
participant call acts as ``participant:<session id>`` inside the tenant taken from the
verified credential.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from osp_store import ParticipantStore, Store, SystemContext, TenantContext

SYSTEM = SystemContext("system:runtime")


def _participant(tenant_id: str, session_id: str | None = None) -> TenantContext:
    return TenantContext(tenant_id, f"participant:{session_id or 'new'}")


class StoreParticipantRepo:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.ps = ParticipantStore(store)

    def create_publication(
        self,
        tenant_id: str,
        actor: str,
        version_id: str,
        slug: str,
        plan: object,
        plan_checksum: str,
        save_mode: str,
        config: object,
        quotas: Mapping[str, int],
        balanced: Mapping[str, tuple[Any, ...]],
    ) -> Any:
        return self.ps.create_publication(
            TenantContext(tenant_id, actor),
            version_id,
            slug,
            plan,
            plan_checksum,
            save_mode,
            config,
            quotas=quotas,
            balanced=balanced,
        )

    def find_publication(self, slug: str, plan_checksum: str | None = None) -> Any:
        return self.ps.find_publication(SYSTEM, slug, plan_checksum)

    def get_publication(self, tenant_id: str, publication_id: str) -> Any:
        return self.ps.get_publication(_participant(tenant_id), publication_id)

    def start(
        self,
        tenant_id: str,
        publication_id: str,
        session_seed: int,
        assigned: Mapping[str, Any],
        token_hash: str,
        url_params: object,
        balanced: tuple[str, ...],
        choose: Any,
    ) -> Any:
        return self.ps.start(
            _participant(tenant_id),
            publication_id,
            session_seed,
            assigned,
            token_hash,
            url_params=url_params,
            balanced=balanced,
            choose=choose,
        )

    def credential_by_token(self, token_hash: str) -> Any:
        return self.ps.credential_by_token(SYSTEM, token_hash)

    def get(self, tenant_id: str, session_id: str) -> Any:
        return self.ps.get(_participant(tenant_id, session_id), session_id)

    def touch(self, tenant_id: str, session_id: str) -> bool:
        return self.ps.touch(_participant(tenant_id, session_id), session_id)

    def write_snapshot(
        self, tenant_id: str, session_id: str, base_revision: int, snapshot: object
    ) -> Any:
        return self.ps.write_snapshot(
            _participant(tenant_id, session_id), session_id, base_revision, snapshot
        )

    def claim_quota(self, tenant_id: str, session_id: str, node_id: str, quota_id: str) -> Any:
        return self.ps.claim_quota(
            _participant(tenant_id, session_id), session_id, node_id, quota_id
        )

    def submit(
        self,
        tenant_id: str,
        session_id: str,
        answers: Mapping[str, Any],
        record: object,
        record_checksum: str,
        realised_orders: object,
        engine_version: str | None,
    ) -> Any:
        return self.ps.submit(
            _participant(tenant_id, session_id),
            session_id,
            answers=answers,
            record=record,
            record_checksum=record_checksum,
            realised_orders=realised_orders,
            engine_version=engine_version,
        )

    def release_inactive(self, cutoff: datetime) -> Any:
        return self.ps.release_inactive(SystemContext("system:release"), cutoff)
