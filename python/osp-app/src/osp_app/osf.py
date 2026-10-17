"""A small OSF client (task OS1): check a token, look up a project, upload files.

OSF (the Open Science Framework, osf.io) takes a **personal access token** as a bearer
header. The token is handed to the command for one call and is never stored, logged or
echoed: it goes into the ``Authorization`` header and nowhere else, and every error
message is built from OSF's status and the project id only.

I/O lives behind ``Transport`` so tests (and other hosts) can swap it: the default uses
the standard library (``urllib``) and no extra dependency. Base URLs come from
``OSP_OSF_API_URL`` / ``OSP_OSF_FILES_URL`` (the defaults are the production servers; OSF's
test servers are ``https://api.test.osf.io/v2`` and ``https://files.test.osf.io/v1``).

Endpoints used (OSF API v2 and its file service, Waterbutler):

- ``GET {api}/users/me/``: who the token belongs to;
- ``GET {api}/nodes/{id}/``: the project's title and visibility;
- ``PUT {files}/resources/{id}/providers/osfstorage/?kind=file&name=…&conflict=replace``:
  create or replace a file in the project's OSF Storage root; the body is the file.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .errors import InvalidRequest, UpstreamError

DEFAULT_API_URL = "https://api.osf.io/v2"
DEFAULT_FILES_URL = "https://files.osf.io/v1"
TIMEOUT_S = 120.0
USER_AGENT = "open-survey-platform-prereg/1"

Transport = Callable[[str, str, Mapping[str, str], bytes | None, float], tuple[int, bytes]]
"""``transport(method, url, headers, body, timeout) -> (status, body)``. Network errors
are raised as ``UpstreamError``; HTTP errors are returned as their status."""

_NODE_ID = re.compile(r"^[A-Za-z0-9]{3,40}$")
_URL_NODE = re.compile(r"osf\.io/([A-Za-z0-9]{3,40})/?")


def api_url() -> str:
    return (os.environ.get("OSP_OSF_API_URL") or DEFAULT_API_URL).rstrip("/")


def files_url() -> str:
    return (os.environ.get("OSP_OSF_FILES_URL") or DEFAULT_FILES_URL).rstrip("/")


def urllib_transport(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https only)
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc.__class__.__name__
        raise UpstreamError(f"OSF could not be reached ({str(reason)[:80]}).") from exc


def node_id_of(value: object) -> str:
    """An OSF project id, from the id itself or a project URL (``https://osf.io/abcde/``)."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequest("Give the OSF project id (or its URL).")
    text = value.strip()
    m = _URL_NODE.search(text)
    if m:
        text = m.group(1)
    if not _NODE_ID.match(text):
        raise InvalidRequest("That is not an OSF project id (letters and digits, like 'ab3de').")
    return text


def check_token(value: object) -> str:
    """A usable token: text, 8-512 characters, no whitespace or control characters (it goes
    into a header). The value itself is never part of a message."""
    if not isinstance(value, str) or not 8 <= len(value) <= 512:
        raise InvalidRequest("Give an OSF personal access token.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) > 126 for ch in value):
        raise InvalidRequest("The OSF token contains characters a token never has.")
    return value


@dataclass(frozen=True)
class OsfUser:
    id: str
    name: str


@dataclass(frozen=True)
class OsfNode:
    id: str
    title: str
    public: bool
    url: str


@dataclass(frozen=True)
class OsfFile:
    name: str
    size: int | None
    id: str | None
    url: str | None  # where the file is seen on OSF (``links.html``), if OSF said


class OsfClient:
    def __init__(
        self,
        token: str,
        *,
        transport: Transport | None = None,
        api: str | None = None,
        files: str | None = None,
        timeout: float = TIMEOUT_S,
    ) -> None:
        self._token = check_token(token)
        self._transport = transport or urllib_transport
        self._api = (api or api_url()).rstrip("/")
        self._files = (files or files_url()).rstrip("/")
        self._timeout = timeout

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.api+json, application/json",
            "User-Agent": USER_AGENT,
        }
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _call(self, method: str, url: str, body: bytes | None, *, what: str, not_found: str) -> Any:
        status, raw = self._transport(
            method,
            url,
            self._headers("application/octet-stream" if body is not None else None),
            body,
            self._timeout,
        )
        if status in (401, 403):
            raise UpstreamError(
                "OSF refused the token (it is wrong, expired, or lacks the 'osf.full_write' scope)."
            )
        if status == 404:
            raise UpstreamError(not_found)
        if status == 413:
            raise UpstreamError("OSF refused the file as too large.")
        if status >= 400:
            raise UpstreamError(f"OSF answered {status} while {what}.")
        try:
            doc = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError) as exc:
            raise UpstreamError("OSF answered with something that is not JSON.") from exc
        return doc if isinstance(doc, Mapping) else {}

    def me(self) -> OsfUser:
        doc = self._call(
            "GET",
            f"{self._api}/users/me/",
            None,
            what="checking the token",
            not_found="OSF did not recognise the token's user.",
        )
        data = _map(doc.get("data"))
        attrs = _map(data.get("attributes"))
        return OsfUser(str(data.get("id") or ""), str(attrs.get("full_name") or ""))

    def node(self, node_id: str) -> OsfNode:
        nid = node_id_of(node_id)
        doc = self._call(
            "GET",
            f"{self._api}/nodes/{quote(nid, safe='')}/",
            None,
            what=f"looking up project '{nid}'",
            not_found=f"OSF has no project '{nid}' that the token can see.",
        )
        data = _map(doc.get("data"))
        attrs = _map(data.get("attributes"))
        links = _map(data.get("links"))
        return OsfNode(
            id=str(data.get("id") or nid),
            title=str(attrs.get("title") or ""),
            public=attrs.get("public") is True,
            url=str(links.get("html") or f"https://osf.io/{nid}/"),
        )

    def upload(self, node_id: str, name: str, content: bytes) -> OsfFile:
        nid = node_id_of(node_id)
        url = (
            f"{self._files}/resources/{quote(nid, safe='')}/providers/osfstorage/"
            f"?kind=file&name={quote(name, safe='')}&conflict=replace"
        )
        doc = self._call(
            "PUT",
            url,
            content,
            what=f"uploading '{name}' to project '{nid}'",
            not_found=f"OSF has no project '{nid}' (with OSF Storage) the token can write to.",
        )
        data = _map(doc.get("data"))
        attrs = _map(data.get("attributes"))
        links = _map(data.get("links"))
        size = attrs.get("size")
        return OsfFile(
            name=str(attrs.get("name") or name),
            size=size if isinstance(size, int) else len(content),
            id=str(data["id"]) if data.get("id") else None,
            url=str(links.get("html")) if links.get("html") else None,
        )


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = [
    "DEFAULT_API_URL",
    "DEFAULT_FILES_URL",
    "OsfClient",
    "OsfFile",
    "OsfNode",
    "OsfUser",
    "Transport",
    "check_token",
    "node_id_of",
    "urllib_transport",
]
