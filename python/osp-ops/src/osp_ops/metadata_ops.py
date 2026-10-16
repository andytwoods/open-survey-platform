"""Metadata ops: title, languages."""

from __future__ import annotations

import copy

from pydantic import Field, JsonValue

from .doc import strip_languages, translations_in
from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op

type Text = str | dict[str, str]


class SetTitle(Params):
    title: Text


@op("set_title", SetTitle, label="Set survey title", area="metadata")
def set_title(ctx: Ctx, p: SetTitle) -> Invocation:
    """Set the survey title (plain text, or one per language)."""
    md = ctx.doc["metadata"]
    old = copy.deepcopy(md["title"])
    md["title"] = copy.deepcopy(p.title)
    return Invocation(op="set_title", params={"title": old})


class SetLanguages(Params):
    languages: list[str] = Field(min_length=1, max_length=200)
    default_language: str | None = None  # None: no explicit default (the first is used)
    cascade: bool = False
    force: bool = False


@op("set_languages", SetLanguages, label="Set languages", area="metadata")
def set_languages(ctx: Ctx, p: SetLanguages) -> Invocation:
    """Set the survey languages (and default language). Dropping a language that still
    has translations is rejected unless `cascade` (deletes those translations) or
    `force` (keeps them; the validator then reports `text.unknown_language`)."""
    md = ctx.doc["metadata"]
    old_langs = list(md["languages"])
    had_default = "defaultLanguage" in md
    old_default = md.get("defaultLanguage")
    dropped = set(old_langs) - set(p.languages)
    cascaded = False
    if dropped and not p.force:
        found = translations_in(ctx.doc, dropped)
        if found and not p.cascade:
            raise OpError(
                "op.dangling_ref",
                f"{len(found)} translation(s) in {', '.join(sorted(dropped))} would be orphaned "
                f"(first at {found[0]}); pass cascade: true to delete them",
                found[0],
            )
        if found:
            strip_languages(ctx.doc, dropped)
            cascaded = True
    md["languages"] = list(p.languages)
    if p.default_language is None:
        md.pop("defaultLanguage", None)
    else:
        md["defaultLanguage"] = p.default_language
    if cascaded or (had_default and old_default is None):
        return REVERSE_PATCH  # an explicit null default, or translations to restore
    params: dict[str, JsonValue] = {"languages": old_langs, "force": True}
    if old_default is not None:
        params["default_language"] = old_default
    return Invocation(op="set_languages", params=params)
