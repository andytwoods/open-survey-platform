"""Media on questions, notes and choices (planning/media.md): images, audio and video.

Two layers, as for the rest of the model:

- :class:`Media` is the pydantic shape (stage 1: ``schema.*`` diagnostics): kind, URL(s),
  the accessibility texts and links, size and duration hints, and the two research flags
  (``mustPlayToEnd``, ``autoplay``).
- :func:`check_media` is the semantic check the validator runs (stage 2: ``media.*``): URL
  rules (https or a same-origin path, no credentials, no pipes), the accessibility
  requirements (alt for images, a transcript for audio, captions for video), which fields fit
  which kind, and, when the deployment's allowed origins are known, that every URL is on one
  of them.

URLs are checked with regular expressions, not ``urllib`` (L1 does no I/O and imports no
network modules). ``url``, ``transcriptUrl`` and ``captionsUrl`` may be per language
(``{lang: url}``), reusing the shape of translatable text.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Annotated, Literal, get_args

from pydantic import Field, StrictInt, StringConstraints

from .diagnostics import pointer
from .model import LanguageTag, Model, Text

type MediaKind = Literal["image", "audio", "video"]
MEDIA_KINDS: tuple[str, ...] = get_args(MediaKind.__value__)

MAX_MEDIA_PER_ITEM = 3
MAX_URL_LENGTH = 2048
MAX_DIMENSION = 8192
MAX_DURATION_SECONDS = 86400

type Url = Annotated[str, StringConstraints(min_length=1, max_length=MAX_URL_LENGTH)]
type LocalisedUrl = Url | dict[LanguageTag, Url]
type MimeType = Annotated[
    str,
    StringConstraints(pattern=r"^(image|audio|video)/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}$"),
]


class Media(Model):
    """One image, audio clip or video.

    - ``url``: where participants load it from: ``https://…`` (no credentials) or a
      same-origin absolute path (``/media/…``). Per language when the stimulus differs.
    - ``alt``: the text alternative of an image (required for images).
    - ``caption``: shown under the media.
    - ``transcriptUrl``: a page or file with the transcript (required for audio, recommended
      for video). ``captionsUrl``: a WebVTT captions file (required for video), per language.
    - ``posterUrl``: the still shown before a video plays.
    - ``width`` / ``height``: pixel hints (both or neither) so the page reserves the space.
    - ``durationSeconds`` / ``mimeType``: hints for the player and the exports.
    - ``mustPlayToEnd``: the participant cannot leave the page before the clip has ended
      (audio/video on a question or note only). ``autoplay``: video only; always muted and
      never under ``prefers-reduced-motion: reduce``.
    """

    kind: MediaKind
    url: LocalisedUrl
    alt: Text | None = None
    caption: Text | None = None
    transcriptUrl: LocalisedUrl | None = None
    captionsUrl: LocalisedUrl | None = None
    posterUrl: Url | None = None
    width: StrictInt | None = Field(default=None, ge=1, le=MAX_DIMENSION)
    height: StrictInt | None = Field(default=None, ge=1, le=MAX_DIMENSION)
    durationSeconds: (
        Annotated[float, Field(gt=0, le=MAX_DURATION_SECONDS, allow_inf_nan=False)] | None
    ) = None
    mimeType: MimeType | None = None
    mustPlayToEnd: bool = False
    autoplay: bool = False


# --- URL rules ------------------------------------------------------------------------------

_HTTPS = re.compile(
    r"^(?P<scheme>https?)://(?P<userinfo>[^/?#@\s]*@)?"
    r"(?P<host>(?:[A-Za-z0-9-]+\.)*[A-Za-z0-9-]+|\[[0-9A-Fa-f:.]+\])(?::(?P<port>\d{1,5}))?"
    r"(?P<rest>[/?#]\S*)?$"
)
_PIPE = re.compile(r"\$\{[^}]*\}")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})
_ORIGIN = re.compile(
    r"^(?P<scheme>https?)://(?P<host>(?:[a-z0-9-]+\.)*[a-z0-9-]+|\[[0-9a-f:.]+\])(?::(?P<port>\d{1,5}))?$"
)


def url_problem(url: str) -> tuple[str, str] | None:
    """Why a media URL is refused as ``(code, message)``, or None when it is fine.

    Accepted: ``https://host[:port]/path`` without credentials, or a same-origin absolute
    path (``/…``, not ``//…``). ``http://localhost`` and ``http://127.0.0.1`` pass with the
    warning ``media.url_insecure`` so local development works; any other ``http://`` is
    refused. Whitespace and ``${…}`` pipes are refused (a URL is never built from answers).
    """
    if _PIPE.search(url):
        return "media.url_pipe", "a media URL cannot pipe answers (${…})"
    if any(ch.isspace() for ch in url):
        return "media.url", "a media URL cannot contain whitespace"
    if url.startswith("/"):
        if url.startswith("//"):
            return (
                "media.url",
                "a scheme-relative URL (//…) is not allowed; give https:// or a path",
            )
        return None
    m = _HTTPS.match(url)
    if not m:
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", url):
            return "media.url", "only https:// URLs or same-origin paths (/media/…) are allowed"
        return (
            "media.url",
            "not a URL: give https://… or a same-origin path such as /media/clip.mp3",
        )
    if m.group("userinfo"):
        return "media.url", "a media URL cannot carry credentials"
    port = m.group("port")
    if port is not None and int(port) > 65535:
        return "media.url", "bad port"
    if m.group("scheme") == "http":
        if m.group("host").lower() in _LOCAL_HOSTS:
            return "media.url_insecure", "http:// is only for local development; use https://"
        return "media.url", "only https:// URLs or same-origin paths (/media/…) are allowed"
    return None


def media_origin(url: str) -> str | None:
    """The serialised origin of an absolute media URL (lowercase host, default port
    dropped), or None for a same-origin path or an unparseable URL."""
    m = _HTTPS.match(url)
    if not m:
        return None
    scheme, host, port = m.group("scheme"), m.group("host").lower(), m.group("port")
    default = "443" if scheme == "https" else "80"
    return f"{scheme}://{host}" + (f":{port}" if port and port != default else "")


def normalise_origins(origins: Iterable[str]) -> frozenset[str]:
    """Deployment origins (``OSP_MEDIA_ORIGINS``) in the form :func:`media_origin` returns.
    Anything that is not one ``scheme://host[:port]`` origin is dropped silently: the
    deployment's own settings check reports it."""
    out: set[str] = set()
    for raw in origins:
        o = raw.strip().lower().rstrip("/")
        m = _ORIGIN.match(o)
        if not m:
            continue
        port = m.group("port")
        default = "443" if m.group("scheme") == "https" else "80"
        out.add(
            f"{m.group('scheme')}://{m.group('host')}"
            + (f":{port}" if port and port != default else "")
        )
    return frozenset(out)


# --- Semantic checks (validator stage 2; codes `media.*` in diagnostics.CODES) ------------

Emit = Callable[[str, str, str], None]


def _urls(value: str | dict[str, str]) -> list[tuple[str, str]]:
    """(url, pointer suffix) pairs of a plain or per-language URL."""
    if isinstance(value, str):
        return [(value, "")]
    return [(v, pointer(k)) for k, v in value.items()]


def check_media(
    media: Media,
    ptr: str,
    *,
    on_choice: bool,
    emit: Emit,
    media_origins: frozenset[str] | None = None,
) -> None:
    """Stage-2 checks for one media object at ``ptr``. ``on_choice``: it sits on a choice
    (image or audio only, no ``mustPlayToEnd``). ``media_origins``: when given, every
    absolute URL must be on one of them (``media.origin_not_allowed``)."""
    kind = media.kind
    url_fields = (
        ("url", media.url),
        ("transcriptUrl", media.transcriptUrl),
        ("captionsUrl", media.captionsUrl),
    )
    for name, value in url_fields:
        if value is None:
            continue
        for url, suffix in _urls(value):
            up = ptr + pointer(name) + suffix
            problem = url_problem(url)
            if problem is not None:
                emit(problem[0], up, problem[1])
                continue
            _origin_check(url, up, emit, media_origins)
    if media.posterUrl is not None:
        up = ptr + "/posterUrl"
        problem = url_problem(media.posterUrl)
        if problem is not None:
            emit(problem[0], up, problem[1])
        else:
            _origin_check(media.posterUrl, up, emit, media_origins)
        if kind != "video":
            emit("media.field_kind", up, "posterUrl is for video only")

    if kind == "image":
        if media.alt is None or _empty_text(media.alt):
            emit(
                "media.alt_missing",
                ptr + "/alt",
                "an image needs alt text (what it shows, for people who cannot see it)",
            )
        if media.captionsUrl is not None:
            emit("media.field_kind", ptr + "/captionsUrl", "captions are for video only")
        if media.mustPlayToEnd:
            emit(
                "media.field_kind",
                ptr + "/mustPlayToEnd",
                "mustPlayToEnd is for audio and video only",
            )
    else:
        if media.alt is not None:
            emit(
                "media.alt_kind",
                ptr + "/alt",
                "alt is for images; give a caption, transcript or captions instead",
            )
        if kind == "audio":
            if media.transcriptUrl is None:
                emit(
                    "media.transcript_missing",
                    ptr + "/transcriptUrl",
                    "an audio clip needs a transcript (transcriptUrl)",
                )
            if media.captionsUrl is not None:
                emit("media.field_kind", ptr + "/captionsUrl", "captions are for video only")
        else:  # video
            if media.captionsUrl is None:
                emit(
                    "media.captions_missing",
                    ptr + "/captionsUrl",
                    "a video needs captions (a WebVTT file in captionsUrl)",
                )
            if media.transcriptUrl is None:
                emit(
                    "media.transcript_recommended",
                    ptr + "/transcriptUrl",
                    "a video should also offer a transcript (transcriptUrl)",
                )
    if media.autoplay and kind != "video":
        emit("media.field_kind", ptr + "/autoplay", "autoplay is for video only (and plays muted)")
    if (media.width is None) != (media.height is None):
        emit("media.size_pair", ptr, "give both width and height, or neither")
    if on_choice:
        if kind == "video":
            emit(
                "media.choice_kind",
                ptr + "/kind",
                "a choice can carry an image or an audio clip, not a video",
            )
        if media.mustPlayToEnd:
            emit(
                "media.must_play_choice",
                ptr + "/mustPlayToEnd",
                "mustPlayToEnd is for a question's or note's media, not a choice's",
            )


def _origin_check(url: str, up: str, emit: Emit, media_origins: frozenset[str] | None) -> None:
    if media_origins is None:
        return
    origin = media_origin(url)
    if origin is None or origin in media_origins:
        return
    allowed = ", ".join(sorted(media_origins)) or "this site only"
    emit(
        "media.origin_not_allowed",
        up,
        f"{origin} is not an allowed media origin for this deployment (allowed: {allowed}); "
        "use a same-origin path or ask the host to add the origin to OSP_MEDIA_ORIGINS",
    )


def _empty_text(text: Text) -> bool:
    values = [text] if isinstance(text, str) else list(text.values())
    return all(not v.strip() for v in values)


__all__ = [
    "MAX_DIMENSION",
    "MAX_DURATION_SECONDS",
    "MAX_MEDIA_PER_ITEM",
    "MAX_URL_LENGTH",
    "MEDIA_KINDS",
    "Media",
    "MediaKind",
    "check_media",
    "media_origin",
    "normalise_origins",
    "url_problem",
]
