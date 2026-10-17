"""osp-host-signing on its own: a fixed test vector, the header set, and that the source
stays importable on the Python versions hosts run (3.9+). The cross-check against
osp-api's verifier is python/osp-api/tests/test_host_signing_crosscheck.py."""

from __future__ import annotations

import ast
import hashlib
import hmac
import sys
from pathlib import Path

import osp_host_signing as s

SECRET = "s" * 32
BODY = b'{"x":1}'
KW = dict(
    key_id="host1",
    secret=SECRET,
    method="post",
    path="/api/surveys/a%20b/export-check?target=lss&a=2&a=1",
    user_id="u-1",
    roles={"z-lab": "viewer", "a-lab": "owner"},
    body=BODY,
    display_name="Zoë O'Neil",
    timestamp=1_800_000_000,
    nonce="AAAAAAAAAAAAAAAAAAAAAA",
)
# Written out by hand from the v1 format in the README, not produced by the module.
CANONICAL = "\n".join(
    [
        "OSP-HMAC-SHA256-v1",
        "POST",
        "/api/surveys/a b/export-check",
        "a=1&a=2&target=lss",
        hashlib.sha256(BODY).hexdigest(),
        "u-1",
        "a-lab:owner,z-lab:viewer",
        "Zo%C3%AB%20O%27Neil",
        "1800000000",
        "AAAAAAAAAAAAAAAAAAAAAA",
    ]
)
VECTOR = "37283cc6bbd537cef9fa77b89c67cd53e847773c9618cbabdd154f3392610ee1"


def test_fixed_vector() -> None:
    h = s.sign_identity_headers(**KW)
    assert hmac.new(SECRET.encode(), CANONICAL.encode(), hashlib.sha256).hexdigest() == VECTOR
    assert h == {
        "X-OSP-Key-Id": "host1",
        "X-OSP-User": "u-1",
        "X-OSP-Roles": "a-lab:owner,z-lab:viewer",
        "X-OSP-Display-Name": "Zo%C3%AB%20O%27Neil",
        "X-OSP-Timestamp": "1800000000",
        "X-OSP-Nonce": "AAAAAAAAAAAAAAAAAAAAAA",
        "X-OSP-Signature": VECTOR,
    }


def test_canonical_pieces() -> None:
    assert s.canonical_query("") == ""
    assert s.canonical_query("b=2&a=x%20y&a=") == "a=&a=x%20y&b=2"
    assert s.format_roles({}) == ""
    assert s.body_digest(b"") == hashlib.sha256(b"").hexdigest()
    assert s.signature(SECRET.encode(), "x") == s.signature(SECRET, "x")


def test_defaults_fresh_nonce_and_no_name() -> None:
    a = s.sign_identity_headers(
        key_id="k", secret=SECRET, method="GET", path="/api/me", user_id="u", roles={}
    )
    b = s.sign_identity_headers(
        key_id="k", secret=SECRET, method="GET", path="/api/me", user_id="u", roles={}
    )
    assert s.H_NAME not in a
    assert a[s.H_NONCE] != b[s.H_NONCE] and len(a[s.H_NONCE]) >= 22
    assert set(a) == set(s.ALL_HEADERS) - {s.H_NAME}


def test_source_parses_as_python_3_9() -> None:
    src = Path(s.__file__).read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 9))


def test_stdlib_only() -> None:
    tree = ast.parse(Path(s.__file__).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    assert roots <= set(sys.stdlib_module_names) | {"__future__"}, roots
