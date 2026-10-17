"""Results aggregation benchmark (task V1, V-D2 targets): 10 k responses first view
< 2 s, 100 k < 15 s. The 100 k run is ``nightly`` (``uv run pytest -m nightly -k bench``).

Synthetic, seeded, fake data only. Rows are bulk-inserted encrypted exactly as the store
writes them (answers + full record), so the timed part is the real request path: one
streaming decrypt pass over every response computing every card of the survey, split
by condition, with intervals.
"""

from __future__ import annotations

import random
import time
import uuid
from datetime import timedelta

import pytest
from osp_app import build_services, make_identity
from osp_app.auth.testing import FakeClock
from osp_store import Keyring, Store, TenantContext, create_engine, migrate
from osp_store import schema as t
from sqlalchemy import insert

from .results_data import SURVEY, T0, publish

KEY = "a" * 43 + "="


def _answers(rng: random.Random) -> dict:
    def a(v):
        return {"state": "answered", "value": v}

    return {
        "fruit": a(rng.choice(["apple", "banana", "cherry"])),
        "sat": a(rng.randint(1, 5)),
        "col": a(rng.sample(["red", "green", "blue"], rng.randint(0, 3))),
        "age": a(rng.randint(18, 90)) if rng.random() < 0.9 else {"state": "unanswered"},
        "price": a(f"{rng.uniform(0, 20):.2f}"),
        "sl": a(rng.randint(0, 10)),
        "big": a(rng.randint(0, 100)),
        "when": a(f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"),
        "why": a("synthetic text " * rng.randint(1, 4)),
        "grid_r1": a(rng.randint(1, 5)),
        "grid_r2": a(rng.randint(1, 5)) if rng.random() < 0.8 else {"state": "irrelevant"},
    }


def populate(store: Store, ctx: TenantContext, version_id: str, checksum: str, n: int) -> None:
    rng = random.Random(42)
    batch_r, batch_rr = [], []
    for i in range(n):
        rid = str(uuid.uuid4())
        answers = _answers(rng)
        arm = rng.choice(["a", "b"])
        record = {
            "record": {
                "format": "osp-response/1",
                "answers": answers,
                "language": "en",
                "end": "complete" if rng.random() < 0.95 else "screened_out",
                "conditions": {"arm": arm},
                "assigned": {"arm": arm},
            },
            "server": {"saveMode": "end-only"},
        }
        a_blob, a_kid = store._enc(answers, "responses", "answers", rid)
        r_blob, r_kid = store._enc(record, "response_records", "record", rid)
        batch_r.append(
            {
                "id": rid, "tenant_id": ctx.tenant_id, "version_id": version_id,
                "version_checksum": checksum, "session_id": None, "allocation_mode": "server",
                "session_seed": i + 1, "assigned_conditions": {"arm": arm},
                "realised_orders": {}, "engine_version": "bench", "answers_ct": a_blob,
                "answers_key_id": a_kid, "started_at": None,
                "submitted_at": T0 + timedelta(seconds=i),
            }
        )  # fmt: skip
        batch_rr.append(
            {"id": rid, "tenant_id": ctx.tenant_id, "record_ct": r_blob, "record_key_id": r_kid}
        )
        if len(batch_r) == 2000 or i == n - 1:
            with store.engine.begin() as conn:
                conn.execute(insert(t.responses), batch_r)
                conn.execute(insert(t.response_records), batch_rr)
            batch_r, batch_rr = [], []


def run_bench(tmp_path, n: int) -> tuple[float, float, dict]:
    engine = create_engine(f"sqlite:///{tmp_path / 'bench.db'}")
    migrate(engine)
    store = Store(engine, Keyring({"k1": KEY}, active="k1"))
    svc = build_services(store, clock=FakeClock())
    owner = svc.admit(make_identity("owner-a", {"lab-a": "owner"}))
    sid = svc.builder.run("survey.create", owner, title="B", survey=SURVEY).survey.id
    ctx = TenantContext(next(iter(owner.roles)), "system:test")
    v = publish(store, ctx, sid, SURVEY)
    populate(store, ctx, v.id, v.checksum, n)
    query = {"split": {"condition": "arm"}, "intervals": True}
    start = time.perf_counter()
    out = svc.builder.run("survey.results_query", owner, survey_id=sid, query=query)
    first = time.perf_counter() - start
    start = time.perf_counter()
    again = svc.builder.run("survey.results_query", owner, survey_id=sid, query=query)
    cached = time.perf_counter() - start
    assert again["cached"] is True
    return first, cached, out


def test_bench_10k(tmp_path):
    first, cached, out = run_bench(tmp_path, 10_000)
    print(f"\nresults 10k: first {first:.2f} s, cached {cached * 1000:.1f} ms")
    assert out["responses"] > 9_000 and len(out["cards"]) == 10
    assert first < 2.0


def test_bench_20_concurrent_identical_queries_scan_once(tmp_path):
    """LV-D3 (task LV2): 20 viewers asking the same thing at the same instant cost one
    decrypt pass (one ``responses.read`` row), and all 20 get the same result."""
    import threading

    engine = create_engine(f"sqlite:///{tmp_path / 'bench.db'}")
    migrate(engine)
    store = Store(engine, Keyring({"k1": KEY}, active="k1"))
    svc = build_services(store, clock=FakeClock())
    owner = svc.admit(make_identity("owner-a", {"lab-a": "owner"}))
    sid = svc.builder.run("survey.create", owner, title="B", survey=SURVEY).survey.id
    ctx = TenantContext(next(iter(owner.roles)), "system:test")
    v = publish(store, ctx, sid, SURVEY)
    populate(store, ctx, v.id, v.checksum, 3_000)
    query = {"split": {"condition": "arm"}, "intervals": True, "live": True}
    viewers = 20
    barrier = threading.Barrier(viewers)
    outs: list[dict] = []
    errors: list[BaseException] = []

    def viewer():
        try:
            barrier.wait(10)
            outs.append(svc.builder.run("survey.results_query", owner, survey_id=sid, query=query))
        except BaseException as exc:  # noqa: BLE001 (reported below)
            errors.append(exc)

    threads = [threading.Thread(target=viewer) for _ in range(viewers)]
    start = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    elapsed = time.perf_counter() - start
    print(f"\nresults 3k x {viewers} concurrent identical: {elapsed:.2f} s")
    assert not errors, errors[0]
    assert len(outs) == viewers
    scans = [a for a in store.list_audit(ctx) if a.action == "responses.read"]
    assert len(scans) == 1, "every viewer scanned"
    assert sum(1 for o in outs if o["cached"] is False) == 1
    assert len({o["generatedAt"] for o in outs}) == 1 and all(o["responses"] > 2_700 for o in outs)
    live = [a for a in store.list_audit(ctx) if a.action == "results.live"]
    assert len(live) == 1  # one actor, one query hash, one window: one row for all 20
    assert not [a for a in store.list_audit(ctx) if a.action == "results.read"]


@pytest.mark.nightly
def test_bench_100k(tmp_path):
    first, cached, out = run_bench(tmp_path, 100_000)
    print(f"\nresults 100k: first {first:.2f} s, cached {cached * 1000:.1f} ms")
    assert out["responses"] > 90_000
    assert first < 15.0
