"""Field encryption at rest: AES-256-GCM, per-row key id, rotation, row binding."""

from __future__ import annotations

from pathlib import Path

import pytest
from osp_store import CryptoError, Keyring, Store, generate_key
from osp_store import schema as t
from osp_store.crypto import aad_for
from sqlalchemy import select, update

KEY_A = "a" * 43 + "="  # test keys only (same as conftest)
KEY_B = "b" * 43 + "="

MARKER = "PLAINTEXT-MARKER-7f3a9c"


def _populate(store: Store, ctx) -> tuple[str, str]:
    survey, _ = store.create_survey(ctx, "S", {"q": "not secret"})
    v = store.publish_version(ctx, survey.id, b"<x/>")
    s = store.start_session(ctx, v.id, 42, {"arm": "A"})
    store.update_session(ctx, s.id, instance={"q1": MARKER + "-instance"})
    r = store.record_response(
        ctx, v.id, {"q1": {"state": "answered", "value": MARKER + "-answer"}}, session_id=s.id
    )
    return s.id, r.id


# -- keyring unit tests ---------------------------------------------------------


def test_roundtrip_and_aad_binding():
    kr = Keyring({"k1": KEY_A}, "k1")
    e = kr.encrypt(b"hello", b"row-1")
    assert e.key_id == "k1" and b"hello" not in e.blob
    assert kr.decrypt("k1", e.blob, b"row-1") == b"hello"
    with pytest.raises(CryptoError):
        kr.decrypt("k1", e.blob, b"row-2")  # copied to another row
    tampered = e.blob[:-1] + bytes([e.blob[-1] ^ 1])
    with pytest.raises(CryptoError):
        kr.decrypt("k1", tampered, b"row-1")
    with pytest.raises(CryptoError):
        kr.decrypt("nope", e.blob, b"row-1")
    with pytest.raises(CryptoError):
        kr.decrypt("k1", b"short", b"row-1")


def test_nonce_is_fresh_each_time():
    kr = Keyring({"k1": KEY_A}, "k1")
    assert kr.encrypt(b"x", b"a").blob != kr.encrypt(b"x", b"a").blob


@pytest.mark.parametrize(
    ("keys", "active"),
    [({}, "k1"), ({"k1": KEY_A}, "k2"), ({"k1": "too-short"}, "k1"), ({"a:b": KEY_A}, "a:b")],
)
def test_bad_keyring_config_is_rejected(keys, active):
    with pytest.raises(CryptoError):
        Keyring(keys, active)


def test_keyring_from_env():
    k = generate_key()
    kr = Keyring.from_env(
        {"OSP_STORE_KEYS": f"old:{KEY_A}, new:{k}", "OSP_STORE_ACTIVE_KEY": "old"}
    )
    assert kr.key_ids == {"old", "new"} and kr.active == "old"
    assert Keyring.from_env({"OSP_STORE_KEYS": f"old:{KEY_A},new:{k}"}).active == "new"
    with pytest.raises(CryptoError):
        Keyring.from_env({})
    with pytest.raises(CryptoError):
        Keyring.from_env({"OSP_STORE_KEYS": "no-colon"})


# -- at rest --------------------------------------------------------------------


def test_encrypted_columns_never_hold_plaintext(store, tenants, engine):
    a, _ = tenants
    _populate(store, a)
    with engine.connect() as conn:
        blobs = [
            bytes(v)
            for table, ct, _kid in t.ENCRYPTED_FIELDS
            for v in conn.execute(select(table.c[ct])).scalars()
            if v is not None
        ]
    assert len(blobs) == 2
    for blob in blobs:
        assert MARKER.encode() not in blob
        assert b"MARKER" not in blob


def test_raw_sqlite_file_does_not_contain_plaintext(store, tenants, backend):
    if backend.sqlite_path is None:
        pytest.skip("file-level check is SQLite only (column check covers Postgres)")
    a, _ = tenants
    _populate(store, a)
    backend.engine.dispose()  # flush and close so the file is complete
    raw = b""
    for suffix in ("", "-wal", "-journal"):
        p = Path(backend.sqlite_path + suffix)
        if p.exists():
            raw += p.read_bytes()
    assert b"not secret" in raw  # sanity: we are reading the real data file
    assert MARKER.encode() not in raw


def test_decrypts_through_the_store(store, tenants):
    a, _ = tenants
    sid, rid = _populate(store, a)
    assert store.get_session(a, sid).instance == {"q1": MARKER + "-instance"}
    assert store.get_response(a, rid).answers["q1"]["value"] == MARKER + "-answer"


def test_ciphertext_moved_to_another_row_fails(store, tenants, engine):
    # Copy tenant A's answers blob into tenant B's response: AAD binds it to A's row.
    a, b = tenants
    _, rid_a = _populate(store, a)
    _, rid_b = _populate(store, b)
    with engine.begin() as conn:
        blob_a = conn.execute(
            select(t.responses.c.answers_ct).where(t.responses.c.id == rid_a)
        ).scalar_one()
        conn.execute(update(t.responses).where(t.responses.c.id == rid_b).values(answers_ct=blob_a))
    with pytest.raises(CryptoError):
        store.get_response(b, rid_b)


def test_key_rotation(engine, tenants, store, clock, sys_ctx):
    a, _ = tenants
    sid, rid = _populate(store, a)
    assert store.count_by_key(sys_ctx) == {"k1": 2}

    # Deploy a new key: old rows stay readable, new writes use k2.
    rotated = Store(engine, Keyring({"k1": KEY_A, "k2": KEY_B}, active="k2"), clock=clock)
    assert rotated.get_response(a, rid).answers["q1"]["value"].startswith(MARKER)
    rotated.update_session(a, sid, current_page="p2")  # no instance change: stays on k1
    assert rotated.count_by_key(sys_ctx) == {"k1": 2}

    assert rotated.rotate_keys(sys_ctx) == 2
    assert rotated.count_by_key(sys_ctx) == {"k2": 2}
    assert rotated.rotate_keys(sys_ctx) == 0  # idempotent

    # k1 can now be retired.
    k2_only = Store(engine, Keyring({"k2": KEY_B}, active="k2"), clock=clock)
    assert k2_only.get_response(a, rid).answers["q1"]["value"].startswith(MARKER)
    assert k2_only.get_session(a, sid).instance == {"q1": MARKER + "-instance"}

    # And a store without the right key cannot read anything.
    with pytest.raises(CryptoError):
        Store(engine, Keyring({"k1": KEY_A}, active="k1"), clock=clock).get_response(a, rid)


def test_aad_names_table_column_and_row():
    assert aad_for("responses", "answers", "r1") == b"osp-store/responses.answers/r1"
