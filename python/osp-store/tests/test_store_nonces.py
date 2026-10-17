"""The shared nonce ledger (D16, migration 0008). SQLite always; Postgres with
`make test-postgres`."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from osp_store import InvalidInput, NonceLedger, downgrade, migrate
from sqlalchemy import inspect

T0 = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
TTL = timedelta(seconds=120)


def test_a_nonce_is_claimed_once_until_it_expires(engine):
    ledger = NonceLedger(engine)
    assert ledger.claim("n-1", T0, TTL) is True
    assert ledger.claim("n-1", T0 + timedelta(seconds=1), TTL) is False
    assert ledger.claim("n-2", T0, TTL) is True
    assert ledger.claim("n-1", T0 + TTL - timedelta(seconds=1), TTL) is False
    assert ledger.claim("n-1", T0 + TTL, TTL) is True  # expired: claimable again


def test_two_ledgers_on_one_database_share_the_nonces(engine):
    a, b = NonceLedger(engine), NonceLedger(engine)  # two workers
    assert a.claim("shared", T0, TTL) is True
    assert b.claim("shared", T0, TTL) is False


def test_expired_rows_are_purged(engine):
    ledger = NonceLedger(engine, purge_every=60)
    for i in range(5):
        assert ledger.claim(f"old-{i}", T0, TTL)
    assert ledger.count() == 5
    assert ledger.claim("fresh", T0 + TTL + timedelta(seconds=1), TTL)  # triggers a purge
    assert ledger.count() == 1
    assert ledger.claim("x", T0 + TTL + timedelta(seconds=2), TTL)  # not due yet
    assert ledger.count() == 2
    assert ledger.purge(T0 + 3 * TTL) == 2


def test_concurrent_claims_have_one_winner(engine):
    ledger = NonceLedger(engine)
    results: list[bool] = []
    lock = threading.Lock()

    def claim() -> None:
        ok = ledger.claim("race", T0, TTL)
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=claim) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(results) == [False] * 7 + [True]


@pytest.mark.parametrize("bad", ["", "x" * 65, None, 7])
def test_bad_nonces_are_refused(engine, bad):
    with pytest.raises(InvalidInput):
        NonceLedger(engine).claim(bad, T0, TTL)


def test_naive_time_is_refused(engine):
    with pytest.raises(InvalidInput):
        NonceLedger(engine).claim("n", datetime(2026, 1, 1), TTL)  # noqa: DTZ001


def test_migration_0008_up_and_down(backend):
    engine = backend.engine
    migrate(engine, "0007_host_identity")
    assert "identity_nonces" not in inspect(engine).get_table_names()
    migrate(engine)
    assert "identity_nonces" in inspect(engine).get_table_names()
    assert NonceLedger(engine).claim("n", T0, TTL)
    downgrade(engine, "0007_host_identity")
    names = set(inspect(engine).get_table_names())
    assert "identity_nonces" not in names and "principals" in names
    migrate(engine)  # and up again, empty
    assert NonceLedger(engine).count() == 0
