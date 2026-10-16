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
