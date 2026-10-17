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
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

PARTICIPANT_PREFIX = "/r"
BUILDER_PREFIX = "/builder"
NO_STORE = "no-store"
IMMUTABLE = "public, max-age=31536000, immutable"
_HASHED = re.compile(r"-[A-Za-z0-9_-]{8}\.(?:js|css)$")


class _CachedStatic(StaticFiles):
    """StaticFiles with cache headers: Vite's content-hashed files (``name-<hash>.js`` /
    ``.css``) are immutable; everything else (index.html, manifest.json, icons) is
    revalidated each time."""

    async def get_response(self, path: str, scope: Scope):  # noqa: ANN201
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
    app: FastAPI, *, participant_dir: Path | None = None, builder_dir: Path | None = None
) -> None:
    if participant_dir is not None:
        index = participant_dir / "index.html"

        @app.get("/s/{slug}", include_in_schema=False)
        def participant_page(slug: str) -> FileResponse:
            return FileResponse(index, headers={"Cache-Control": NO_STORE})

        app.mount(
            PARTICIPANT_PREFIX,
            _CachedStatic(directory=participant_dir, html=True),
            name="participant-app",
        )
    if builder_dir is not None:
        app.mount(BUILDER_PREFIX, _CachedStatic(directory=builder_dir), name="builder-files")
