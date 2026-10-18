"""Instrument stubs (planning/question-bank.md §1.7, §7.5; task QB5): metadata, response
format and scoring recipe for instruments the project may **not** bundle (class C "ask the
holder" and class D "proprietary"), with **no item text**. A lab that holds a licence
pastes its own copy of the items into the builder's "Add a licensed instrument privately"
wizard; `compose.py` turns a stub plus the lab's text into a private bank item.

One `osp-instrument-stub/0.1` document per instrument under `stubs/<id>.json`, read from
the package's own data and nothing else. Stubs are not bank items: they carry no
fragment, so `licence-policy.toml` `[instruments]` (which judges bundled item text) does
not apply to them, and nothing in them is the rights holder's expression.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any, Literal

from osp_spec.model import Model
from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

STUBS = "stubs"
STUB_VERSION = "osp-instrument-stub/0.1"

# "licensed": proprietary or electronic redistribution forbidden (class D); "ask": free for
# non-commercial research but redistribution not granted (class C, A*).
Terms = Literal["ask", "licensed"]
ResponseKind = Literal["shared", "per-item"]
Aggregate = Literal["sum", "mean"]


class StubHolder(Model):
    name: StrictStr = Field(min_length=1)
    url: StrictStr | None = None


class StubCitation(Model):
    text: StrictStr = Field(min_length=1)
    doi: StrictStr | None = None


class StubResponse(Model):
    """The response format: one scale shared by every item, or item-specific options
    (each item has its own wording for the same score range)."""

    kind: ResponseKind
    min: StrictInt
    max: StrictInt

    @model_validator(mode="after")
    def _range(self) -> StubResponse:
        if self.max <= self.min:
            raise ValueError("max must be greater than min")
        if self.max - self.min > 20:
            raise ValueError("a response scale has at most 21 points")
        return self


class StubScoring(Model):
    """The recipe `compose_fragment` turns into computed variables. Indices are 1-based
    item numbers. `total`: a variable over every item; `subscales`: one per named set.
    `offset` is added to a sum before `factor` (a decimal text) multiplies it."""

    aggregate: Aggregate | None = "sum"
    reversed: list[StrictInt] = Field(default_factory=list)
    subscales: dict[StrictStr, list[StrictInt]] = Field(default_factory=dict)
    total: StrictBool = True
    offset: StrictInt = 0
    factor: StrictStr | None = None
    text: StrictStr = Field(min_length=1)


class InstrumentStub(Model):
    stubVersion: Literal["osp-instrument-stub/0.1"]
    id: StrictStr = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    title: StrictStr = Field(min_length=1, max_length=200)
    abbreviation: StrictStr = Field(min_length=1, max_length=40)
    description: StrictStr = Field(min_length=1)
    tags: list[StrictStr] = Field(default_factory=list, max_length=20)
    terms: Terms
    holder: StubHolder
    citation: StubCitation
    itemCount: StrictInt = Field(ge=1, le=200)
    response: StubResponse
    scoring: StubScoring
    note: StrictStr | None = None

    @model_validator(mode="after")
    def _indices(self) -> InstrumentStub:
        n = self.itemCount
        sets = [("reversed", self.scoring.reversed), *self.scoring.subscales.items()]
        for name, items in sets:
            if not items and name != "reversed":
                raise ValueError(f"subscale {name!r} is empty")
            bad = [i for i in items if not 1 <= i <= n]
            if bad:
                raise ValueError(f"{name}: item numbers {bad} are outside 1-{n}")
            if len(set(items)) != len(items):
                raise ValueError(f"{name}: an item number repeats")
        if not self.scoring.total and not self.scoring.subscales:
            raise ValueError("a recipe scores a total, subscales or both")
        return self


@cache
def _documents() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    root = resources.files(__package__).joinpath(STUBS)
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".json"):
            doc = json.loads(entry.read_text(encoding="utf-8"))
            out[doc["id"]] = doc
    return out


def stub_ids() -> list[str]:
    return sorted(_documents())


def load_stub_document(stub_id: str) -> dict[str, Any] | None:
    """The raw stub document (a fresh copy), or None."""
    doc = _documents().get(stub_id)
    return json.loads(json.dumps(doc)) if doc is not None else None


def load_stub(stub_id: str) -> InstrumentStub | None:
    doc = _documents().get(stub_id)
    return InstrumentStub.model_validate(doc) if doc is not None else None


def load_stubs() -> list[InstrumentStub]:
    """Every stub as a validated model, in id order."""
    return [InstrumentStub.model_validate(_documents()[i]) for i in stub_ids()]


__all__ = [
    "STUB_VERSION",
    "InstrumentStub",
    "StubCitation",
    "StubHolder",
    "StubResponse",
    "StubScoring",
    "load_stub",
    "load_stub_document",
    "load_stubs",
    "stub_ids",
]
