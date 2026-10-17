# osp-host-signing

Sign the `X-OSP-*` identity headers that a host (your Django, Flask or Rails-fronting app)
sends to Open Survey Platform's `osp-api`. Standard library only, Python 3.9+, MIT.

osp-api has no sign-in of its own. Your app signs the researcher in, then forwards each
builder API call with these headers, HMAC-signed with a secret it shares with osp-api
(`OSP_IDENTITY_KEYS=kid:secret`). osp-api verifies them with this same package
(`osp_api.signing` re-exports it), so the two sides cannot drift apart.

## Install

It is not on PyPI. Install it from the repository:

```sh
pip install "osp-host-signing @ git+https://github.com/andytwoods/open-survey-platform#subdirectory=python/osp-host-signing"
```

Pin a commit or tag in production (`...open-survey-platform@<sha>#subdirectory=...`).
With uv: `uv add "osp-host-signing @ git+https://github.com/andytwoods/open-survey-platform#subdirectory=python/osp-host-signing"`.

## Use

```python
from osp_host_signing import sign_identity_headers

headers = sign_identity_headers(
    key_id="host1",  # the kid of one OSP_IDENTITY_KEYS entry
    secret=SECRET,  # its secret (at least 32 bytes)
    method="POST",
    path="/api/surveys",  # as osp-api sees it, query included if any
    body=body_bytes,  # send exactly these bytes
    user_id=str(request.user.pk),  # 1-64 of A-Z a-z 0-9 . _ ~ @ + -
    roles={"psych-lab": "editor"},  # lab id -> "owner", "editor" or "viewer"
    display_name=request.user.get_full_name() or None,
)
# Strip any X-OSP-* header the browser sent, add these, forward to osp-api.
```

It returns `X-OSP-Key-Id`, `X-OSP-User`, `X-OSP-Roles`, `X-OSP-Display-Name` (only with a
name), `X-OSP-Timestamp`, `X-OSP-Nonce` and `X-OSP-Signature`. osp-api refuses a request
whose signature is wrong, more than 60 seconds old, or whose nonce it has seen before.

## The format (v1)

The signature is hex HMAC-SHA256 over these lines, joined with `\n`:

```text
OSP-HMAC-SHA256-v1
METHOD                 upper case
/path                  percent-decoded, as osp-api routes it
a=1&b=2                query pairs sorted, RFC 3986-encoded ('' if none)
sha256(body) hex       of the exact bytes sent
user                   X-OSP-User value
roles                  X-OSP-Roles value (lab:role,... sorted by lab id)
display name           X-OSP-Display-Name value as sent ('' if absent)
timestamp              X-OSP-Timestamp value (Unix seconds)
nonce                  X-OSP-Nonce value (128 random bits, base64url)
```

`canonical_string`, `canonical_query`, `body_digest`, `signature` and `format_roles` are
exported for hosts in other languages that want to test their own implementation against
this one. The full hosting guide is `docs/hosting.md` in the repository.
