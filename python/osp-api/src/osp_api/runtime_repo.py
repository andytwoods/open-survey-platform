"""Re-export: the store-backed ``ParticipantRepo`` lives in ``osp_app.runtime_repo``
(publish needs it too)."""

from osp_app.runtime_repo import StoreParticipantRepo

__all__ = ["StoreParticipantRepo"]
