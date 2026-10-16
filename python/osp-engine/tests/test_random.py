"""Tests for osp_engine.random: Enketo parity, properties, hostile inputs."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from osp_engine.random import (
    MAX_SEED,
    NODE_SEED_MAX,
    InvalidSeedError,
    RandomInputError,
    _permute,
    assign,
    check_seed,
    node_seed,
    randomize,
    shuffle,
)

DATA = Path(__file__).parent / "data" / "e5_enketo_integer_seeds.json"
ROWS = json.loads(DATA.read_text())["rows"]

seeds = st.integers(min_value=1, max_value=MAX_SEED)
texts = st.text(max_size=40)


# --- Enketo parity (spike E5 evidence) -------------------------------------------------------


def test_parity_data_is_the_full_integer_subset():
    assert len(ROWS) == 3600  # 900 integer seeds x lengths 3, 5, 10, 26
    assert {n for _, _, n, _ in ROWS} == {3, 5, 10, 26}


def test_parity_positive_integer_seeds_public_api():
    rows = [r for r in ROWS if r[1] >= 1]
    mismatches = [r for r in rows if randomize(range(r[2]), r[1]) != r[3]]
    assert len({r[1] for r in rows}) == 799  # small 1-99, random31, large (2^31..2^53)
    assert mismatches == []


def test_parity_all_integer_seeds_raw_algorithm():
    # 0 and negatives are rejected by policy, but the port must still match Enketo there.
    mismatches = [r for r in ROWS if _permute(list(range(r[2])), r[1]) != r[3]]
    assert len({r[1] for r in ROWS}) == 900
    assert mismatches == []


def test_known_vectors():
    # Spot values from the evidence file, so a regression shows a readable diff.
    assert _permute([0, 1, 2], 0) == [2, 1, 0]
    assert randomize([0, 1, 2], 5080271880759129) == [2, 0, 1]


# --- properties -------------------------------------------------------------------------------


@given(st.lists(st.integers(), max_size=60), seeds)
def test_shuffle_is_a_permutation(items, seed):
    out = shuffle(items, seed)
    assert Counter(out) == Counter(items)
    assert len(out) == len(items)


@given(st.lists(st.integers(), max_size=30), seeds)
def test_shuffle_is_deterministic_and_pure(items, seed):
    before = list(items)
    assert shuffle(items, seed) == shuffle(items, seed) == randomize(items, seed)
    assert items == before


@given(st.integers(min_value=1, max_value=60), seeds)
def test_shuffle_of_distinct_items_hits_every_index(n, seed):
    assert sorted(shuffle(range(n), seed)) == list(range(n))


@given(texts, seeds, texts)
def test_node_seed_is_a_valid_seed_and_deterministic(version, session, node):
    s = node_seed(version, session, node)
    assert 1 <= s <= NODE_SEED_MAX
    assert check_seed(s) == s
    assert node_seed(version, session, node) == s


@given(texts, seeds, st.lists(texts, min_size=2, max_size=8, unique=True), st.data())
def test_changing_one_node_id_leaves_other_streams_alone(version, session, ids, data):
    items = list(range(10))
    before = {i: shuffle(items, node_seed(version, session, i)) for i in ids}
    k = data.draw(st.integers(min_value=0, max_value=len(ids) - 1))
    renamed = ids[k] + "-renamed"
    after_ids = [renamed if j == k else i for j, i in enumerate(ids)]
    after = {i: shuffle(items, node_seed(version, session, i)) for i in after_ids}
    for j, i in enumerate(ids):
        if j != k and i != renamed:
            assert after[i] == before[i]
    assert node_seed(version, session, renamed) != node_seed(version, session, ids[k])


def test_streams_differ_across_nodes_versions_and_sessions():
    base = node_seed("v1", 123, "q1")
    assert node_seed("v1", 123, "q2") != base
    assert node_seed("v2", 123, "q1") != base
    assert node_seed("v1", 124, "q1") != base
    # Netstring framing: shifting a boundary character changes the hash.
    assert node_seed("v1", 123, "q1") != node_seed("v", 123, "1q1")
    assert node_seed("a|b", 1, "c") != node_seed("a", 1, "b|c")


def test_node_seed_formula_is_the_documented_one():
    def ns(s: str) -> bytes:
        b = s.encode()
        return f"{len(b)}:".encode() + b + b","

    msg = ns("osp-node-seed/1") + ns("v1") + ns("123") + ns("q1")
    expected = int.from_bytes(hashlib.sha256(msg).digest()[:8], "big") % (2**31 - 2) + 1
    assert node_seed("v1", 123, "q1") == expected
    # Pin the value too: changing it breaks every published XLSForm's seeds.
    assert node_seed("v1", 123, "q1") == 1443069630


def test_node_seeds_spread_over_independent_nodes():
    # 200 nodes in one session: no structure in the first draw (unlike raw consecutive seeds).
    firsts = [shuffle(range(5), node_seed("v1", 7, f"n{i}"))[0] for i in range(200)]
    assert len(set(firsts)) == 5


@pytest.mark.parametrize(
    "weights",
    [None, [1, 1], [1, 2, 7], [0.25, 0.25, 0.5], [3, 0, 1]],
)
def test_assign_distribution_matches_weights(weights):
    n = 10_000
    conds = ["A", "B"] if weights is None else ["A", "B", "C"][: len(weights)]
    counts = Counter(assign(conds, weights, node_seed("v1", s, "cond")) for s in range(1, n + 1))
    ws = [1] * len(conds) if weights is None else weights
    total = sum(ws)
    for c, w in zip(conds, ws, strict=True):
        p = w / total
        if p == 0:
            assert counts[c] == 0
            continue
        sigma = math.sqrt(n * p * (1 - p)) or 1
        assert abs(counts[c] - n * p) < 4.5 * sigma, (c, counts)


@given(st.lists(st.integers(min_value=0, max_value=50), min_size=1, max_size=8), seeds)
def test_assign_is_deterministic_and_never_picks_zero_weight(ws, seed):
    if sum(ws) == 0:
        with pytest.raises(RandomInputError):
            assign(list(range(len(ws))), ws, seed)
        return
    k = assign(list(range(len(ws))), ws, seed)
    assert k == assign(list(range(len(ws))), ws, seed)
    assert ws[k] > 0


def test_assign_single_condition():
    assert assign(["only"], None, 1) == "only"
    assert assign(["only"], [5], MAX_SEED) == "only"


# --- hostile inputs ---------------------------------------------------------------------------

BAD_SEEDS = [
    0,
    -1,
    -(2**31),
    True,
    False,
    MAX_SEED + 1,
    2**64,
    10**400,
    1.0,
    3.5,
    float("nan"),
    float("inf"),
    "123",
    "sess-1",
    "",
    None,
    b"1",
    [1],
    1 + 0j,
]


@pytest.mark.parametrize("seed", BAD_SEEDS, ids=repr)
def test_bad_seeds_are_rejected_cleanly(seed):
    for call in (
        lambda: check_seed(seed),
        lambda: randomize([1, 2, 3], seed),
        lambda: shuffle([1, 2, 3], seed),
        lambda: assign(["A", "B"], None, seed),
        lambda: node_seed("v1", seed, "q1"),
    ):
        with pytest.raises(InvalidSeedError) as e:
            call()
        assert e.value.code.startswith("seed.")


@given(st.one_of(st.floats(), st.text(), st.booleans(), st.none(), st.integers(max_value=0)))
def test_any_non_seed_raises_typed_error(seed):
    with pytest.raises(InvalidSeedError):
        check_seed(seed)


@pytest.mark.parametrize(
    ("version", "node", "code"),
    [
        (1, "q1", "survey_version.not_string"),
        ("v1", None, "node_id.not_string"),
        ("v1", b"q1", "node_id.not_string"),
        ("v1", "\ud800", "node_id.not_utf8"),
        ("\udfff", "q1", "survey_version.not_utf8"),
    ],
)
def test_node_seed_bad_strings(version, node, code):
    with pytest.raises(RandomInputError) as e:
        node_seed(version, 1, node)
    assert e.value.code == code


@pytest.mark.parametrize(
    ("conditions", "weights", "code"),
    [
        ([], None, "conditions.empty"),
        ("AB", None, "conditions.not_sequence"),
        ({"A", "B"}, None, "conditions.not_sequence"),
        (["A", "B"], [1], "weights.length"),
        (["A", "B"], [0, 0], "weights.all_zero"),
        (["A", "B"], [1, -1], "weights.negative"),
        (["A", "B"], [1, float("nan")], "weights.not_finite"),
        (["A", "B"], [1, float("inf")], "weights.not_finite"),
        (["A", "B"], [1, True], "weights.not_number"),
        (["A", "B"], [1, "2"], "weights.not_number"),
        (["A", "B"], "12", "weights.not_sequence"),
        (["A", "B"], 3, "weights.not_sequence"),
    ],
)
def test_assign_bad_inputs(conditions, weights, code):
    with pytest.raises(RandomInputError) as e:
        assign(conditions, weights, 42)
    assert e.value.code == code
