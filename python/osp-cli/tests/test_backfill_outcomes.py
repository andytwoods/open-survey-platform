"""``osp-cli backfill-outcomes`` (task EN4): the one-off after migration 0011."""

from __future__ import annotations

import json
import uuid

import pytest
from osp_cli.main import main, open_services
from osp_store import ParticipantStore, SystemContext, TenantContext, generate_key
from osp_store import schema as t
from sqlalchemy import select, update


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("OSP_STORE_KEYS", f"k1:{generate_key()}")
    monkeypatch.delenv("OSP_STORE_ACTIVE_KEY", raising=False)


def _submitted(store, ctx, outcomes: list[str]) -> list[str]:
    """One submitted response per outcome, through the participant store, as the runtime
    would store them (record ``end`` + outcome column)."""
    ps = ParticipantStore(store)
    survey, _ = store.create_survey(ctx, "S", {"blocks": []})
    version = store.publish_version(ctx, survey.id, b"", meta={})
    pub = ps.create_publication(ctx, version.id, "bf", {"checksum": "x"}, "x", "end-only", {})
    ids = []
    for i, outcome in enumerate(outcomes):
        s = ps.start(ctx, pub.id, 7, {}, uuid.uuid4().hex * 2)
        r = ps.submit(
            ctx,
            s.id,
            answers={"q1": {"state": "answered", "value": i}},
            record={"record": {"end": outcome}, "server": {}},
            record_checksum=f"{i:064d}",
            realised_orders={},
            engine_version=None,
        )
        ids.append(r.response_id)
    return ids


def test_backfill_fills_null_outcomes_from_the_records(tmp_path, keys, capsys):
    db = f"sqlite:///{tmp_path / 'bf.db'}"
    services = open_services(db)
    store = services.store
    tenant = store.create_tenant(SystemContext("system:test"), "Lab")
    ctx = TenantContext(tenant.id, "researcher")
    ids = _submitted(store, ctx, ["complete", "screened_out", "complete"])
    with store.engine.begin() as conn:  # rows as they look before migration 0011
        conn.execute(update(t.responses).values(outcome=None))
    store.engine.dispose()

    assert main(["backfill-outcomes", "--db", db, "--batch", "2"]) == 0
    assert json.loads(capsys.readouterr().out) == {"scanned": 3, "updated": 3}
    with store.engine.connect() as conn:
        rows = conn.execute(
            select(t.responses.c.id, t.responses.c.outcome).order_by(t.responses.c.id)
        ).all()
    assert dict(rows) == dict(zip(ids, ["complete", "screened_out", "complete"], strict=True))

    assert main(["backfill-outcomes", "--db", db]) == 0  # nothing left: a no-op
    assert json.loads(capsys.readouterr().out) == {"scanned": 0, "updated": 0}


def test_backfill_needs_a_database_and_keys(tmp_path, keys, monkeypatch, capsys):
    assert main(["backfill-outcomes", "--db", "sqlite:///x.db", "--batch", "0"]) == 2
    assert "--batch" in capsys.readouterr().err
    monkeypatch.delenv("OSP_STORE_KEYS")
    assert main(["backfill-outcomes", "--db", f"sqlite:///{tmp_path / 'k.db'}"]) == 2
    assert "OSP_STORE_KEYS" in capsys.readouterr().err
