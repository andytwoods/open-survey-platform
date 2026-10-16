"""Pure parts of osp-runtime: token bucket, config parsing, record validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from osp_runtime import InvalidPayload, RuntimeConfig, TokenBucket, validate_record


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_token_bucket_refills_with_the_injected_clock():
    clock = Clock()
    tb = TokenBucket(3, 1, clock)
    assert [tb.allow("k") for _ in range(4)] == [True, True, True, False]
    assert tb.allow("other")  # buckets are per key
    clock.now += timedelta(seconds=1)
    assert tb.allow("k") and not tb.allow("k")
    clock.now -= timedelta(hours=1)  # a clock going backwards adds nothing
    assert not tb.allow("k")


def test_token_bucket_memory_is_bounded():
    tb = TokenBucket(1, 0, Clock(), max_keys=10)
    for i in range(100):
        tb.allow(f"k{i}")
    assert len(tb._buckets) <= 10


CFG = {
    "surveyVersion": "1",
    "assignments": [
        {"variable": "f", "levels": ["a", "b"], "seedNode": "n/f", "weights": [1, 3]},
        {"variable": "arm", "levels": [1, 2], "method": "balanced", "seedNode": "n/arm"},
    ],
    "quotas": [
        {"node": "qc1", "quota": "w", "limit": 5},
        {"node": "qc2", "quota": "w", "limit": 5},
    ],
}


def test_config_resume_expiry_is_optional():
    assert RuntimeConfig.from_json(CFG).resume_expiry_days is None
    assert "resumeExpiryDays" not in RuntimeConfig.from_json(CFG).to_json()
    cfg = RuntimeConfig.from_json({**CFG, "resumeExpiryDays": 7})
    assert cfg.resume_expiry_days == 7
    assert RuntimeConfig.from_json(cfg.to_json()) == cfg


def test_session_policy_separates_the_two_timers():
    from osp_runtime import SessionPolicy

    p = SessionPolicy()
    assert (p.resume_expiry, p.release_after) == (timedelta(days=30), timedelta(hours=24))


def test_config_round_trip():
    cfg = RuntimeConfig.from_json(CFG)
    assert RuntimeConfig.from_json(cfg.to_json()) == cfg
    assert cfg.balanced == {"arm": (1, 2)}
    assert cfg.quota_limits == {"w": 5}
    assert cfg.quota_by_node["qc2"].quota == "w"


@pytest.mark.parametrize(
    "patch",
    [
        {"surveyVersion": ""},
        {"saveMode": "sometimes"},
        {"assignments": [{"variable": "f", "levels": [], "seedNode": "x"}]},
        {"assignments": [{"variable": "f", "levels": ["a", "a"], "seedNode": "x"}]},
        {"assignments": [{"variable": "f", "levels": ["a"], "seedNode": "x", "weights": [0]}]},
        {"assignments": [{"variable": "f", "levels": [True], "seedNode": "x"}]},
        {"assignments": [{"variable": "f", "levels": ["a"]}]},
        {
            "assignments": [
                {"variable": "f", "levels": ["a"], "seedNode": "x", "method": "b", "weights": [1]}
            ]
        },  # fmt: skip
        {"quotas": [{"node": "q", "quota": "w", "limit": -1}]},
        {
            "quotas": [
                {"node": "q", "quota": "w", "limit": 1},
                {"node": "r", "quota": "w", "limit": 2},
            ]
        },
        {"resumeExpiryDays": 0},
        {"resumeExpiryDays": "30"},
        {"resumeExpiryDays": True},
        {"resumeExpiryDays": 3651},
        "not an object",
    ],
)
def test_config_rejects_bad_input(patch):
    data = patch if isinstance(patch, str) else {**CFG, **patch}
    with pytest.raises(InvalidPayload):
        RuntimeConfig.from_json(data)


SESS = SimpleNamespace(id="s1", assigned={"f": "a"})
PUB = SimpleNamespace(plan_checksum="abc")
GOOD = {
    "sessionId": "s1",
    "planChecksum": "abc",
    "assigned": {"f": "a"},
    "answers": {"q1": {"state": "answered", "value": 1}, "q2": {"state": "irrelevant"}},
}


def test_validate_record_accepts_a_good_record():
    answers, orders, engine = validate_record({**GOOD, "engineVersion": "0.1"}, SESS, PUB)
    assert answers == GOOD["answers"] and orders == {} and engine == "0.1"


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"sessionId": "other"}, "submit.session"),
        ({"planChecksum": "zzz"}, "submit.plan"),
        ({"assigned": {"f": "b"}}, "submit.assignment"),
        ({"answers": {"q": {"state": "maybe"}}}, "payload.invalid"),
        ({"answers": {"q": {"state": "unanswered", "value": 3}}}, "payload.invalid"),
        ({"orders": []}, "payload.invalid"),
        ({"events": {}}, "payload.invalid"),
        ({"engineVersion": 5}, "payload.invalid"),
    ],
)
def test_validate_record_rejects(patch, code):
    with pytest.raises(InvalidPayload) as e:
        validate_record({**GOOD, **patch}, SESS, PUB)
    assert e.value.code == code


class FakeRepo:
    """Just enough of ParticipantRepo for auth and submit."""

    def __init__(self, clock: Clock, config: dict) -> None:
        self.cred = SimpleNamespace(
            session_id="s1",
            tenant_id="t1",
            last_active_at=clock.now,
            submitted_at=None,
            expired_at=None,
            publication_id="p1",
        )
        self.pub = SimpleNamespace(plan_checksum="abc", config=config, slug="x", plan={})
        self.sess = SimpleNamespace(
            id="s1",
            assigned={"f": "a"},
            publication_id="p1",
            save_mode="every-page",
            session_seed=7,
            revision=0,
            snapshot=None,
            submitted_at=None,
        )
        self.submits: list[bool] = []

    def credential_by_token(self, _h):
        return self.cred

    def get_publication(self, _t, _p):
        return self.pub

    def get(self, _t, _s):
        return self.sess

    def touch(self, _t, _s):
        return True

    def submit(self, *_args, late=False):
        self.submits.append(late)
        at = datetime(2026, 1, 1, tzinfo=UTC)
        return SimpleNamespace(status="ok", response_id="r1", submitted_at=at, late=late)


@pytest.mark.parametrize(
    ("days", "idle", "late"), [(None, 29, False), (None, 30, True), (2, 2, True), (2, 1, False)]
)
def test_service_token_expiry_and_late_submit(days, idle, late):
    from osp_runtime import SessionExpired, SessionService

    clock = Clock()
    cfg = {"surveyVersion": "1", **({"resumeExpiryDays": days} if days else {})}
    repo = FakeRepo(clock, cfg)
    svc = SessionService(repo, clock=clock)  # type: ignore[arg-type]
    clock.now += timedelta(days=idle)
    if late:
        with pytest.raises(SessionExpired):
            svc.resume("tok")
    else:
        assert svc.resume("tok").session_id == "s1"
    ack = svc.submit("s1", "tok", GOOD)  # always accepted (S-2)
    assert ack.late is late and repo.submits == [late]


def test_service_submit_after_holds_released_is_late():
    from osp_runtime import SessionService

    clock = Clock()
    repo = FakeRepo(clock, {"surveyVersion": "1"})
    repo.cred.expired_at = clock.now  # holds released, token still fresh
    svc = SessionService(repo, clock=clock)  # type: ignore[arg-type]
    assert svc.resume("tok").session_id == "s1"
    assert svc.submit("s1", "tok", GOOD).late is True


def test_quota_result_uses_the_engine_words_and_reads_the_old_ones():
    from osp_runtime.session import quota_result

    assert [quota_result(v) for v in ("open", "admitted", "full")] == ["open", "open", "full"]
    for bad in ("closed", None, 1):
        with pytest.raises(InvalidPayload):
            quota_result(bad)


def _snap(rev, *events):
    return {"revision": rev, "data": {"events": [{"t": e} for e in events]}}


@pytest.mark.parametrize(
    ("mine", "server", "older"),
    [
        (_snap(1, "a"), _snap(3, "a", "b", "c"), True),
        (_snap(3, "a", "b", "c"), _snap(3, "a", "b", "c"), True),  # identical
        (_snap(2, "a", "x"), _snap(3, "a", "b", "c"), False),  # diverged
        (_snap(4, "a", "b", "c", "d"), _snap(3, "a", "b", "c"), False),  # newer
        (_snap(5, "a"), _snap(3, "a", "b"), False),  # newer engine revision
        ({"p": 1}, _snap(3, "a"), False),  # not an engine snapshot
        (_snap(1, "a"), None, False),
        (_snap(1, "a"), {"data": {"events": "no"}}, False),
    ],
)
def test_is_older_prefix(mine, server, older):
    from osp_runtime.session import is_older_prefix

    assert is_older_prefix(mine, server) is older


def test_local_copy_comes_from_plan_settings():
    from osp_runtime.session import local_copy

    assert local_copy({"settings": {"localCopy": "memory"}}) == "memory"
    assert local_copy({"settings": {"localCopy": "browser"}}) == "browser"
    assert local_copy({}) == local_copy(None) == local_copy({"settings": 3}) == "browser"


def test_embed_theme_sets_plan_theme_and_recomputes_the_checksum():
    import json
    from pathlib import Path

    from osp_runtime.plan import checksum, embed_theme
    from osp_spec.theme import PRESETS

    schema = json.loads(
        (Path(__file__).resolve().parents[3] / "contract" / "runtime-plan.schema.json").read_text()
    )
    assert "theme" in schema["properties"] and "theme" not in schema["required"]
    plan = {"checksum": "sha256:old", "settings": {}}
    theme = PRESETS["clean"].model_dump(mode="json", by_alias=True)
    out = embed_theme(plan, theme)
    assert out["theme"] == theme and "theme" not in plan  # the input is not mutated
    assert out["checksum"] == checksum(out) != checksum({**plan, "theme": None})
    assert all(k in theme for k in schema["$defs"]["theme"]["required"])
