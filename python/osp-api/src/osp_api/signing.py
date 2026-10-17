"""Signed identity headers (D2): re-exported from the standalone ``osp-host-signing``
package (``python/osp-host-signing``), the single implementation. Hosts install that
package instead of osp-api; osp-api's verifier (:mod:`osp_api.identity`) uses it too."""

from osp_host_signing import (
    ALL_HEADERS,
    H_KEY_ID,
    H_NAME,
    H_NONCE,
    H_ROLES,
    H_SIGNATURE,
    H_TIMESTAMP,
    H_USER,
    SCHEME,
    body_digest,
    canonical_query,
    canonical_string,
    format_roles,
    sign_identity_headers,
    signature,
)

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
