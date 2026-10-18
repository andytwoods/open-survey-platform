"""Drafts (optimistic concurrency + op log) and immutable published versions."""

from __future__ import annotations

import hashlib

import pytest
from osp_store import (
    InvalidInput,
    OpRecord,
    RevisionConflict,
    StoreError,
    canonical_json,
    checksum,
)
from osp_store import schema as t
from sqlalchemy import text, update

SURVEY = {"id": "s1", "title": "Mood", "blocks": [{"id": "b1", "questions": []}], "é": 1.5}


def test_create_and_read_draft_is_opaque(store, tenants):
    a, _ = tenants
    survey, draft = store.create_survey(a, "Mood", SURVEY)
    assert draft.revision == 0
    got = store.get_draft(a, survey.id)
    assert got.body == SURVEY
    assert got.revision == 0
    assert store.list_surveys(a) == [survey]


def test_save_draft_bumps_revision_and_logs_ops(store, tenants, clock):
    a, _ = tenants
    survey, _ = store.create_survey(a, "Mood", SURVEY)
    ops = [
        OpRecord("question.add", {"id": "q1"}, {"op": "question.remove", "id": "q1"}),
        OpRecord("question.rename", {"id": "q1", "to": "Q"}, {"id": "q1", "to": ""}),
    ]
    clock.advance(minutes=1)
    d1 = store.save_draft(a, survey.id, {**SURVEY, "v": 1}, base_revision=0, ops=ops, txn_id="t1")
    d2 = store.save_draft(a, survey.id, {**SURVEY, "v": 2}, base_revision=1)
    assert (d1.revision, d2.revision) == (1, 2)
    assert store.get_draft(a, survey.id).body["v"] == 2
    log = store.list_ops(a, survey.id)
    assert [(e.revision, e.seq, e.txn_id, e.op_id) for e in log] == [
        (1, 0, "t1", "question.add"),
        (1, 1, "t1", "question.rename"),
    ]
    assert log[0].inverse == {"op": "question.remove", "id": "q1"}
    assert log[0].actor == a.actor
    assert store.list_ops(a, survey.id, after_revision=1) == []


def test_stale_revision_conflicts_and_writes_nothing(store, tenants):
    a, _ = tenants
    survey, _ = store.create_survey(a, "Mood", SURVEY)
    store.save_draft(a, survey.id, {"v": 1}, base_revision=0)
    with pytest.raises(RevisionConflict) as exc:
        store.save_draft(a, survey.id, {"v": "lost"}, 0, ops=[OpRecord("x", {}, {})])
    assert (exc.value.expected, exc.value.current) == (0, 1)
    assert store.get_draft(a, survey.id).body == {"v": 1}
    assert store.list_ops(a, survey.id) == []


@pytest.mark.parametrize("bad", [{1, 2}, float("nan"), object(), {"k": b"bytes"}])
def test_non_json_body_is_rejected(store, tenants, bad):
    a, _ = tenants
    with pytest.raises(InvalidInput):
        store.create_survey(a, "x", bad)


def test_bad_revision_and_ops_are_rejected(store, tenants):
    a, _ = tenants
    survey, _ = store.create_survey(a, "Mood", SURVEY)
    for rev in (-1, "0", 1.0, None, True):
        with pytest.raises(InvalidInput):
            store.save_draft(a, survey.id, {}, rev)
    with pytest.raises(InvalidInput):
        store.save_draft(a, survey.id, {}, 0, ops=[{"op_id": "x"}])


def test_publish_freezes_draft_with_checksum(store, tenants):
    a, _ = tenants
    survey, _ = store.create_survey(a, "Mood", SURVEY)
    v1 = store.publish_version(a, survey.id, b"<h:html/>", meta={"pyxform": "4.0"})
    assert v1.number == 1
    assert v1.body == SURVEY
    expected = hashlib.sha256(canonical_json(SURVEY).encode()).hexdigest()
    assert v1.checksum == expected == checksum(SURVEY)
    assert v1.xform == b"<h:html/>"
    assert v1.meta == {"pyxform": "4.0"}

    # Editing the draft afterwards never changes the published version.
    store.save_draft(a, survey.id, {"changed": True}, 0)
    assert store.get_version(a, v1.id) == v1
    v2 = store.publish_version(a, survey.id, b"<x/>")
    assert v2.number == 2
    assert v2.body == {"changed": True}
    assert [v.number for v in store.list_versions(a, survey.id)] == [1, 2]


def test_checksum_is_key_order_independent():
    assert checksum({"a": 1, "b": [1, 2]}) == checksum({"b": [1, 2], "a": 1})
    assert checksum({"a": 1}) != checksum({"a": 2})


def test_store_has_no_way_to_mutate_a_version(store):
    names = [n for n in dir(store) if "version" in n and not n.startswith("_")]
    assert sorted(names) == [
        "add_bank_version",  # bank item versions (QB4): added and read, never changed
        "get_bank_version",
        "get_version",
        "list_bank_versions",
        "list_versions",
        "publish_version",
    ]


def test_tampered_version_body_is_detected(store, tenants, engine):
    a, _ = tenants
    survey, _ = store.create_survey(a, "Mood", SURVEY)
    v = store.publish_version(a, survey.id, b"x")
    with engine.begin() as conn:
        conn.execute(update(t.versions).where(t.versions.c.id == v.id).values(body='{"evil":1}'))
    with pytest.raises(StoreError, match="checksum"):
        store.get_version(a, v.id)


def test_version_body_stored_as_canonical_text(store, tenants, engine):
    a, _ = tenants
    survey, _ = store.create_survey(a, "Mood", SURVEY)
    v = store.publish_version(a, survey.id, b"x")
    with engine.connect() as conn:
        raw = conn.execute(
            text("SELECT body FROM versions WHERE id = :id"), {"id": v.id}
        ).scalar_one()
    assert raw == canonical_json(SURVEY)
