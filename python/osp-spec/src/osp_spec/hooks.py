"""Researcher hooks (runtime-design.md §7a): the survey-level ``hooks`` manifest.

The manifest is the researcher's script plus everything it declares: which events it
handles (with the questions and variables each handler reads and the hook variables it
writes), the URL parameters ``onStart`` may see, the redirect templates and the parent
message types. Its shape is ``HookManifest`` in ``web/hooks-sandbox/src/manifest.ts``; the
limits here mirror that file. The compiled plan carries the manifest unchanged
(``osp_runtime.plan``), inside the plan checksum, so the code is versioned with the survey.

Two layers, as for the rest of the model:

- :class:`Hooks` is the pydantic shape (stage 1: ``schema.*`` diagnostics);
- :func:`check_hooks` is the semantic check the validator runs (stage 2: ``hooks.*``):
  reads refer to answerable questions or variables, writes only to hook variables (none
  exist in osp-survey/0.1 yet, so a write is always an error here, exactly as the hook host
  would refuse it), redirect templates and the parent origin follow the host's rules.

What a hook may do at run time (actions, timeouts, flow-critical detection) is the hook
host's business, not the spec's.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Annotated, Literal, get_args

from pydantic import (
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from .diagnostics import pointer
from .model import Identifier, Model

HOOKS_FORMAT = "osp-hooks/1"
type HookEvent = Literal[
    "onStart",
    "onResume",
    "onPageInit",
    "onPageShown",
    "onAnswer",
    "onPageNext",
    "onBack",
    "onValidationError",
    "onBeforeSubmit",
    "onSubmitted",
]
HOOK_EVENTS: tuple[str, ...] = get_args(HookEvent.__value__)

# Limits mirrored from web/hooks-sandbox/src/manifest.ts.
DEFAULT_HOOK_TIMEOUT_MS = 2000
MAX_HOOK_TIMEOUT_MS = 5000
MAX_HOOK_SOURCE_BYTES = 256 * 1024
MAX_PAYLOAD_DEPTH = 4
DEFAULT_PARAM_PATTERN = "[A-Za-z0-9_-]{1,64}"

type Name = Annotated[str, StringConstraints(min_length=1, max_length=256)]


# --- Model ------------------------------------------------------------------------------


class HookHandler(Model):
    """One event handler's declarations. ``ctx.results`` and ``ctx.vars`` hold only the
    ``reads``; ``setVariable`` is accepted only for the ``writes``."""

    reads: list[Identifier]
    writes: list[Identifier]
    timeoutMs: StrictInt | None = Field(default=None, ge=1, le=MAX_HOOK_TIMEOUT_MS)


class HookRedirectParam(Model):
    # The value must match it in full. Default: DEFAULT_PARAM_PATTERN.
    pattern: StrictStr | None = None


class HookRedirect(Model):
    """An end-of-survey redirect template: an https URL with ``{name}`` placeholders after
    the origin, each declared in ``params``."""

    url: StrictStr
    params: dict[Name, HookRedirectParam]


class HookStringSchema(Model):
    type: Literal["string"]
    maxLength: StrictInt | None = Field(default=None, ge=0)
    pattern: StrictStr | None = None
    enum: list[StrictStr] | None = None


class HookNumberSchema(Model):
    type: Literal["number", "integer"]
    minimum: StrictInt | Annotated[StrictFloat, Field(allow_inf_nan=False)] | None = None
    maximum: StrictInt | Annotated[StrictFloat, Field(allow_inf_nan=False)] | None = None


class HookBooleanSchema(Model):
    type: Literal["boolean"]


class HookNullSchema(Model):
    type: Literal["null"]


class HookObjectSchema(Model):
    """Objects never allow undeclared properties."""

    type: Literal["object"]
    properties: dict[Name, HookPayloadSchema]
    required: list[Name] | None = None


class HookArraySchema(Model):
    type: Literal["array"]
    items: HookPayloadSchema
    maxItems: StrictInt = Field(ge=0, le=1000)


type HookPayloadSchema = Annotated[
    HookStringSchema
    | HookNumberSchema
    | HookBooleanSchema
    | HookNullSchema
    | HookObjectSchema
    | HookArraySchema,
    Field(discriminator="type"),
]


def _depth(schema: object, depth: int) -> int:
    if isinstance(schema, HookObjectSchema):
        return max([depth, *(_depth(v, depth + 1) for v in schema.properties.values())])
    if isinstance(schema, HookArraySchema):
        return _depth(schema.items, depth + 1)
    return depth


class HookParent(Model):
    """Messages the hooks may post to the embedding page: one origin, typed messages."""

    origin: StrictStr
    messages: dict[Name, HookPayloadSchema]

    @model_validator(mode="after")
    def _bounded_depth(self) -> HookParent:
        for name, schema in self.messages.items():
            if _depth(schema, 0) > MAX_PAYLOAD_DEPTH:
                raise ValueError(
                    f"message schema {name!r} is nested deeper than {MAX_PAYLOAD_DEPTH}"
                )  # noqa: E501
        return self


class Hooks(Model):
    """The hook manifest (``osp-hooks/1``)."""

    format: Literal["osp-hooks/1"]
    source: StrictStr  # the script; it registers handlers with `osp.on(event, fn)`
    handlers: dict[HookEvent, HookHandler]
    urlParams: list[Name] | None = None  # URL parameters `onStart` may see
    redirects: dict[Name, HookRedirect] | None = None
    parent: HookParent | None = None
    # Checksum of `source` an owner confirmed for data exports (redirects, parent messages).
    exportsConfirmedFor: StrictStr | None = None

    @field_validator("source")
    @classmethod
    def _source_size(cls, source: str) -> str:
        if len(source.encode("utf-8", "surrogatepass")) > MAX_HOOK_SOURCE_BYTES:
            raise ValueError(f"source is larger than {MAX_HOOK_SOURCE_BYTES} bytes")
        return source


for _m in (HookObjectSchema, HookArraySchema, HookParent, Hooks):
    _m.model_rebuild()


def hooks_json(hooks: Hooks) -> dict[str, object]:
    """The manifest as plan JSON: what the hook host (``checkManifest``) reads. Unset
    optional fields are left out (the host treats ``null`` and absent differently)."""
    return hooks.model_dump(mode="json", by_alias=True, exclude_none=True)


# --- Semantic checks (validator stage 2; codes `hooks.*` in diagnostics.CODES) ----------

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]{0,31})\}")
_ORIGIN = re.compile(r"^(https?)://((?:[a-z0-9-]+\.)*[a-z0-9-]+|\[[0-9a-f:.]+\])(?::(\d{1,5}))?$")
_HTTPS_URL = re.compile(
    r"^https://((?:[A-Za-z0-9-]+\.)*[A-Za-z0-9-]+|\[[0-9A-Fa-f:.]+\])(?::(\d{1,5}))?(/\S*)?$"
)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


def placeholders(url: str) -> list[str]:
    return _PLACEHOLDER.findall(url)


def _pattern_ok(pattern: str | None) -> bool:
    try:
        re.compile(f"(?:{DEFAULT_PARAM_PATTERN if pattern is None else pattern})")
    except re.error, OverflowError, RecursionError:
        return False
    return True


def origin_ok(origin: str) -> bool:
    """One serialised origin (``scheme://host[:port]``, lowercase host, no default port):
    https, or http on localhost for development. As ``checkOrigin`` in manifest.ts."""
    m = _ORIGIN.match(origin)
    if not m:
        return False
    scheme, host, port = m.groups()
    if port is not None and (int(port) > 65535 or port == ("443" if scheme == "https" else "80")):
        return False
    return scheme == "https" or host in _LOCAL_HOSTS


def redirect_problem(t: HookRedirect) -> str | None:
    """Why a redirect template is refused, or None. As ``checkTemplate`` in manifest.ts."""
    names = placeholders(t.url)
    if len(set(names)) != len(names):
        return "duplicate placeholder"
    if len(t.params) != len(names) or any(n not in t.params for n in names):
        return "placeholders and params differ"
    for n in names:
        if not _pattern_ok(t.params[n].pattern):
            return f"bad pattern for {n}"
    filled = _PLACEHOLDER.sub("x", t.url)
    m = _HTTPS_URL.match(filled)
    if not m:
        return "not https" if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", filled) else "not a URL"
    host, port, _path = m.groups()
    origin = f"https://{host.lower()}" + (f":{port}" if port and port != "443" else "")
    # Placeholders only after the origin: a value can never change where the URL goes.
    first = t.url.find("{")
    if 0 <= first < len(origin) + 1:
        return "placeholder in the origin"
    if not t.url.startswith(origin + "/"):
        return "origin must be followed by a path"
    return None


def check_hooks(
    hooks: Hooks,
    *,
    readable: Iterable[str],
    hook_variables: Iterable[str],
    emit: Callable[[str, str, str], None],
) -> None:
    """Stage-2 checks for a manifest. ``readable`` are the ids a handler may read (answerable
    questions, matrix rows and variables); ``hook_variables`` the ids it may write.
    ``emit(code, pointer, message)`` records a diagnostic."""
    can_read = set(readable)
    can_write = set(hook_variables)
    for ev, h in hooks.handlers.items():
        hp = pointer("hooks", "handlers", ev)
        for i, rid in enumerate(h.reads):
            if rid not in can_read:
                emit(
                    "hooks.unknown_ref",
                    hp + pointer("reads", i),
                    f"'{rid}' is not a question or variable a hook can read",
                )
        for i, wid in enumerate(h.writes):
            if wid not in can_write:
                emit(
                    "hooks.write_target",
                    hp + pointer("writes", i),
                    f"'{wid}' is not a hook variable (hooks may set only hook variables; "
                    "osp-survey/0.1 declares none yet)",
                )
            elif ev == "onSubmitted":
                emit(
                    "hooks.write_target",
                    hp + pointer("writes", i),
                    "onSubmitted may not write variables",
                )
    for rid, t in (hooks.redirects or {}).items():
        if (why := redirect_problem(t)) is not None:
            emit("hooks.redirect", pointer("hooks", "redirects", rid), f"redirect template: {why}")
    if hooks.parent is not None and not origin_ok(hooks.parent.origin):
        emit(
            "hooks.parent_origin",
            pointer("hooks", "parent", "origin"),
            "must be one https origin such as https://lab.example.org (http only on localhost)",
        )


__all__ = [
    "DEFAULT_HOOK_TIMEOUT_MS",
    "DEFAULT_PARAM_PATTERN",
    "HOOKS_FORMAT",
    "HOOK_EVENTS",
    "MAX_HOOK_SOURCE_BYTES",
    "MAX_HOOK_TIMEOUT_MS",
    "MAX_PAYLOAD_DEPTH",
    "HookArraySchema",
    "HookBooleanSchema",
    "HookEvent",
    "HookHandler",
    "HookNullSchema",
    "HookNumberSchema",
    "HookObjectSchema",
    "HookParent",
    "HookPayloadSchema",
    "HookRedirect",
    "HookRedirectParam",
    "HookStringSchema",
    "Hooks",
    "check_hooks",
    "hooks_json",
    "origin_ok",
    "placeholders",
    "redirect_problem",
]
