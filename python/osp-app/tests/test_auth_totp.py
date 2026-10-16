from __future__ import annotations

import base64
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from osp_app.auth import totp
from osp_app.auth.testing import FakeRandom

# RFC 6238 appendix B, SHA-1 secret "12345678901234567890", 8 digits.
RFC_KEY = b"12345678901234567890"
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize(("ts", "expected"), RFC_VECTORS)
def test_rfc6238_vectors(ts, expected):
    assert totp.hotp(RFC_KEY, ts // 30, digits=8) == expected


def test_rfc4226_hotp_vectors():
    expected = ["755224", "287082", "359152", "969429", "338314"]
    assert [totp.hotp(RFC_KEY, i) for i in range(5)] == expected


def test_totp_uses_base32_secret():
    secret = base64.b32encode(RFC_KEY).decode()
    assert totp.totp(secret, at(59)) == "287082"


def at(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, UTC)


def test_verify_window_plus_minus_one_step():
    secret = totp.generate_secret(FakeRandom())
    now = 1_800_000_000
    for offset, ok in [(-60, False), (-30, True), (0, True), (30, True), (60, False)]:
        code = totp.totp(secret, at(now + offset))
        assert (totp.verify(secret, code, at(now), last_step=None) is not None) is ok, offset


def test_replay_rejected():
    secret = totp.generate_secret(FakeRandom())
    now = at(1_800_000_000)
    code = totp.totp(secret, now)
    step = totp.verify(secret, code, now, last_step=None)
    assert step is not None
    assert totp.verify(secret, code, now, last_step=step) is None
    # an older code inside the window is also rejected once a newer one was used
    older = totp.totp(secret, at(1_800_000_000 - 30))
    assert totp.verify(secret, older, now, last_step=step) is None


@pytest.mark.parametrize("bad", [None, 123456, "", "12345", "1234567", "abcdef", "١٢٣٤٥٦"])
def test_malformed_codes(bad):
    secret = totp.generate_secret(FakeRandom())
    assert totp.verify(secret, bad, at(1_800_000_000), last_step=None) is None


def test_bad_secret_does_not_crash():
    assert totp.verify("!!!not-base32", "123456", at(0), last_step=None) is None


def test_provisioning_uri():
    uri = totp.provisioning_uri("JBSWY3DPEHPK3PXP", "ada@example.org", "Open Survey Platform")
    parsed = urlparse(uri)
    assert parsed.scheme == "otpauth" and parsed.netloc == "totp"
    assert parsed.path == "/Open%20Survey%20Platform:ada@example.org"
    q = parse_qs(parsed.query)
    assert q["secret"] == ["JBSWY3DPEHPK3PXP"]
    assert q["issuer"] == ["Open Survey Platform"]
    assert q["digits"] == ["6"] and q["period"] == ["30"]


def test_recovery_codes_hashed_and_single_match():
    codes = totp.generate_recovery_codes(FakeRandom())
    assert len(codes) == totp.RECOVERY_CODE_COUNT == len(set(codes))
    hashes = tuple(totp.hash_recovery_code(c) for c in codes)
    assert all(c.replace("-", "") not in "".join(hashes) for c in codes)
    assert totp.match_recovery_code(codes[3], hashes) == hashes[3]
    assert totp.match_recovery_code(codes[3].lower().replace("-", " "), hashes) == hashes[3]
    assert totp.match_recovery_code("AAAA-AAAA-AAAA-AAAA", hashes) is None
    assert totp.match_recovery_code(None, hashes) is None
    assert totp.match_recovery_code("short", hashes) is None
