"""Optional static serving (task H2b): the participant app and the builder page files, for
a deployment where osp-api runs as its own container and the host proxies to it.

Off unless configured. ``OSP_PARTICIPANT_DIR`` (a ``web/runtime/dist``) serves:

- ``/r/...``: the app's files (the build uses ``base: '/r/'``); ``/r/`` is its index;
- ``/s/{slug}``: the same ``index.html``, the participant link (docs/hosting.md §4).

``index.html`` carries its own CSP meta tag and is sent ``no-store``; the hashed files under
``/r/assets/`` are immutable. ``OSP_BUILDER_DIR`` (a ``web/builder/build``) serves those
files read-only under ``/builder/``: static JS, CSS, icons and ``manifest.json``, so a host
can fetch them or point its static prefix there. The builder pages themselves are still
rendered by the host, behind its sign-in (docs/hosting.md §2).

Media origins (planning/media.md §2.3): the baked policy allows images and media from the
page's own origin only, and a ``<meta>`` policy cannot be loosened by a header, so
``index.html`` is rewritten at serve time: every origin in ``OSP_MEDIA_ORIGINS`` is added
to its ``img-src`` and ``media-src`` directives (:func:`media_csp`). A host that serves the
file itself applies the same change (``GET /api/meta/media-policy`` gives the directives).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

PARTICIPANT_PREFIX = "/r"
BUILDER_PREFIX = "/builder"
NO_STORE = "no-store"
IMMUTABLE = "public, max-age=31536000, immutable"
_HASHED = re.compile(r"-[A-Za-z0-9_-]{8}\.(?:js|css)$")
_CSP_META = re.compile(
    r"""(<meta\s+http-equiv=["']Content-Security-Policy["']\s+content=["'])([^"']*)(["'])""",
    re.IGNORECASE,
)
# What the participant page needs for its own media before any deployment origin is added.
MEDIA_DIRECTIVES = {"img-src": ("'self'", "data:", "blob:"), "media-src": ("'self'", "blob:")}


def media_csp(policy: str, origins: Sequence[str]) -> str:
    """``policy`` with ``origins`` appended to its ``img-src`` and ``media-src`` directives
    (a missing directive is added with the page's own sources). Other directives are kept
    as they are. Idempotent."""
    directives = [d.strip() for d in policy.split(";") if d.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for d in directives:
        name, _, rest = d.partition(" ")
        if name in MEDIA_DIRECTIVES:
            seen.add(name)
            sources = rest.split()
            sources += [o for o in origins if o not in sources]
            out.append(" ".join([name, *sources]))
        else:
            out.append(d)
    for name, base in MEDIA_DIRECTIVES.items():
        if name not in seen:
            out.append(" ".join([name, *base, *origins]))
    return "; ".join(out)


def media_sources(origins: Sequence[str]) -> dict[str, str]:
    """The ``img-src`` and ``media-src`` source lists a host writes for ``origins``."""
    return {name: " ".join([*base, *origins]) for name, base in MEDIA_DIRECTIVES.items()}


def rewrite_index(html: str, origins: Sequence[str]) -> str:
    """``index.html`` with its CSP meta tag's media directives widened to ``origins``."""
    if not origins:
        return html
    return _CSP_META.sub(lambda m: m.group(1) + media_csp(m.group(2), origins) + m.group(3), html)


class _CachedStatic(StaticFiles):
    """StaticFiles with cache headers: Vite's content-hashed files (``name-<hash>.js`` /
    ``.css``) are immutable; everything else (index.html, manifest.json, icons) is
    revalidated each time. With ``index`` set, the index page is served from that string
    (the CSP-rewritten ``index.html``)."""

    def __init__(self, *, directory: Path, html: bool = False, index: str | None = None) -> None:
        super().__init__(directory=directory, html=html)
        self.index = index

    async def get_response(self, path: str, scope: Scope):  # noqa: ANN201
        if self.index is not None and path.replace("\\", "/") in ("", ".", "index.html"):
            return HTMLResponse(self.index, headers={"Cache-Control": NO_STORE})
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            hashed = _HASHED.search(path.replace("\\", "/")) is not None
            response.headers["Cache-Control"] = IMMUTABLE if hashed else "no-cache"
            if path.endswith(".html") or path in ("", "."):
                response.headers["Cache-Control"] = NO_STORE
        return response


def check_participant_dir(path: Path) -> str | None:
    """Why ``path`` can't be served as the participant app, or None."""
    if not (path / "index.html").is_file():
        return f"{path} has no index.html (build it: pnpm -C web/runtime build)"
    return None


def check_builder_dir(path: Path) -> str | None:
    """Why ``path`` can't be served as the builder files, or None."""
    if not (path / "manifest.json").is_file():
        return f"{path} has no manifest.json (build it: make web-build)"
    return None


def mount_static(
    app: FastAPI,
    *,
    participant_dir: Path | None = None,
    builder_dir: Path | None = None,
    media_origins: Sequence[str] = (),
) -> None:
    if participant_dir is not None:
        index_path = participant_dir / "index.html"
        index = (
            rewrite_index(index_path.read_text(encoding="utf-8"), media_origins)
            if media_origins
            else None
        )

        @app.get("/s/{slug}", include_in_schema=False, response_model=None)
        def participant_page(slug: str) -> FileResponse | HTMLResponse:
            if index is not None:
                return HTMLResponse(index, headers={"Cache-Control": NO_STORE})
            return FileResponse(index_path, headers={"Cache-Control": NO_STORE})

        app.mount(
            PARTICIPANT_PREFIX,
            _CachedStatic(directory=participant_dir, html=True, index=index),
            name="participant-app",
        )
    if builder_dir is not None:
        app.mount(BUILDER_PREFIX, _CachedStatic(directory=builder_dir), name="builder-files")
