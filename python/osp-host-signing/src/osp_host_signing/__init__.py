"""osp-host-signing: signed identity headers, v1 (planning/pages-split.md D2).

One canonical form for both sides. A host signs with :func:`sign_identity_headers`;
osp-api verifies with the same :func:`canonical_string` (``osp_api.signing`` re-exports
this module, so there is one implementation). Standard library only, Python 3.9+: a host
installs this package without osp-api or its web framework.

Headers the host sends on every request it forwards::

    X-OSP-Key-Id        which shared secret signed it (OSP_IDENTITY_KEYS=kid:secret,...)
    X-OSP-User          the host's opaque user id
    X-OSP-Roles         lab:role,... (sorted by lab id; empty: no labs)
    X-OSP-Display-Name  optional; UTF-8, percent-encoded (so any name fits in a header)
    X-OSP-Timestamp     Unix seconds; must be within 60 s of osp-api's clock
    X-OSP-Nonce         128 random bits, base64url; each one is accepted once
    X-OSP-Signature     hex HMAC-SHA256(secret, canonical string)

Canonical string (lines joined with ``\\n``, no trailing newline)::

    OSP-HMAC-SHA256-v1
    METHOD                      upper case
    /path                       percent-decoded, as osp-api routes it (e.g. /api/surveys)
    a=1&b=2                     query pairs sorted, RFC 3986-encoded ('' if none)
    sha256(body) hex            of the exact bytes sent (empty body: sha256(b""))
    user                        X-OSP-User value
    roles                       X-OSP-Roles value
    display name                X-OSP-Display-Name value as sent ('' if absent)
    timestamp                   X-OSP-Timestamp value
    nonce                       X-OSP-Nonce value
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Mapping
from urllib.parse import parse_qsl, quote, unquote, urlsplit

__all__ = [
    "ALL_HEADERS",
    "H_KEY_ID",
    "H_NAME",
    "H_NONCE",
    "H_ROLES",
    "H_SIGNATURE",
    "H_TIMESTAMP",
    "H_USER",
    "SCHEME",
    "body_digest",
    "canonical_query",
    "canonical_string",
    "format_roles",
    "sign_identity_headers",
    "signature",
]

SCHEME = "OSP-HMAC-SHA256-v1"
H_KEY_ID = "X-OSP-Key-Id"
H_USER = "X-OSP-User"
H_ROLES = "X-OSP-Roles"
H_NAME = "X-OSP-Display-Name"
H_TIMESTAMP = "X-OSP-Timestamp"
H_NONCE = "X-OSP-Nonce"
H_SIGNATURE = "X-OSP-Signature"
ALL_HEADERS = (H_KEY_ID, H_USER, H_ROLES, H_NAME, H_TIMESTAMP, H_NONCE, H_SIGNATURE)


def canonical_query(query: str) -> str:
    """Query pairs, sorted by (name, value), each part RFC 3986-encoded."""
    pairs = parse_qsl(query, keep_blank_values=True)
    return "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(pairs))


def body_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_string(
    *,
    method: str,
    path: str,
    query: str,
    body_sha256: str,
    user: str,
    roles: str,
    display_name: str,
    timestamp: str,
    nonce: str,
) -> str:
    return "\n".join(
        (
            SCHEME,
            method.upper(),
            unquote(path),
            canonical_query(query),
            body_sha256,
            user,
            roles,
            display_name,
            timestamp,
            nonce,
        )
    )


def signature(secret: str | bytes, canonical: str) -> str:
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    return hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def format_roles(roles: Mapping[str, str]) -> str:
    return ",".join(f"{lab}:{role}" for lab, role in sorted(roles.items()))


def sign_identity_headers(
    *,
    key_id: str,
    secret: str | bytes,
    method: str,
    path: str,
    user_id: str,
    roles: Mapping[str, str],
    body: bytes = b"",
    display_name: str | None = None,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """The ``X-OSP-*`` headers for one request. ``path`` is what osp-api will see, and may
    carry the query (``/api/surveys/x/export-check?target=lss``). Send ``body`` byte for
    byte as signed. Strip any ``X-OSP-*`` the browser sent before adding these."""
    parts = urlsplit(path)
    name = "" if display_name is None else quote(display_name, safe="")
    ts = str(int(time.time()) if timestamp is None else int(timestamp))
    nonce = nonce or secrets.token_urlsafe(16)
    role_text = format_roles(roles)
    canonical = canonical_string(
        method=method,
        path=parts.path,
        query=parts.query,
        body_sha256=body_digest(body),
        user=user_id,
        roles=role_text,
        display_name=name,
        timestamp=ts,
        nonce=nonce,
    )
    headers = {
        H_KEY_ID: key_id,
        H_USER: user_id,
        H_ROLES: role_text,
        H_TIMESTAMP: ts,
        H_NONCE: nonce,
        H_SIGNATURE: signature(secret, canonical),
    }
    if name:
        headers[H_NAME] = name
    return headers
