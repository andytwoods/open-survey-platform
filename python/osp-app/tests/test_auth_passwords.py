from __future__ import annotations

import pytest
from osp_app.auth import PasswordHasher, PasswordPolicy
from osp_app.auth.passwords import DEFAULT_MIN_LENGTH, _blocklist
from osp_app.auth.testing import cheap_hasher

policy = PasswordPolicy()
GOOD_PASSWORD = "plum tractor violet ninety"


def test_good_passphrase_accepted():
    assert policy.problems(GOOD_PASSWORD, email="ada@example.org") == []


@pytest.mark.parametrize("pw", ["", "a", "x" * (DEFAULT_MIN_LENGTH - 1), "short"])
def test_too_short(pw):
    assert policy.problems(pw)


def test_too_long():
    assert policy.problems("ab" * 200)


def test_no_composition_rules():
    # all lowercase, no digits or symbols: fine if long and not common
    assert policy.problems("lantern orbit pickle meadow") == []


@pytest.mark.parametrize(
    "pw",
    ["passwordpassword", "PasswordPassword", "correct horse battery staple", "123456789012345"],
)
def test_blocklist(pw):
    assert any("common" in p for p in policy.problems(pw))


def test_blocklist_bundled_and_nonempty():
    assert len(_blocklist()) > 100


@pytest.mark.parametrize(
    "pw", ["aaaaaaaaaaaaaaaa", "abcabcabcabcabcabc", "abcdefghijklmnopq", "9876543210"]
)
def test_repetitive_or_sequential(pw):
    assert PasswordPolicy(min_length=8).problems(pw)


def test_context_words():
    assert policy.problems("ada.lovelace and some more words", email="ada.lovelace@example.org")
    assert policy.problems("my opensurvey login phrase")


@pytest.mark.parametrize("bad", [None, 12345678901234567, b"bytes-password-long", ["x"]])
def test_non_string_rejected_not_crash(bad):
    assert policy.problems(bad)


def test_unicode_nfkc_normalised_for_hash():
    h = cheap_hasher()
    composed = "café crème brûlée tonight"
    decomposed = "café crème brûlée tonight"
    assert h.verify(h.hash(composed), decomposed)


def test_hash_is_argon2id_and_verifies():
    h = cheap_hasher()
    digest = h.hash(GOOD_PASSWORD)
    assert digest.startswith("$argon2id$")
    assert h.verify(digest, GOOD_PASSWORD)
    assert not h.verify(digest, GOOD_PASSWORD + "x")


@pytest.mark.parametrize("garbage", ["", "not-a-hash", "$argon2id$v=19$broken"])
def test_verify_garbage_hash_is_false(garbage):
    assert cheap_hasher().verify(garbage, GOOD_PASSWORD) is False
    assert cheap_hasher().needs_rehash(garbage) is True


def test_needs_rehash_when_params_change():
    old = cheap_hasher().hash(GOOD_PASSWORD)
    stronger = PasswordHasher(time_cost=2, memory_cost=16, parallelism=1)
    assert stronger.needs_rehash(old)
    assert not cheap_hasher().needs_rehash(old)


def test_deployment_sets_min_length_from_env():
    assert PasswordPolicy.from_env({"OSP_PASSWORD_MIN_LENGTH": "12"}).min_length == 12
    assert PasswordPolicy.from_env({}).min_length == DEFAULT_MIN_LENGTH
    assert (
        PasswordPolicy.from_env({"OSP_PASSWORD_MIN_LENGTH": "nonsense"}).min_length
        == DEFAULT_MIN_LENGTH
    )
