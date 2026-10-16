"""What the server needs to know about a published survey, beside the opaque plan.

The runtime plan (``plan.py``, task R1) is opaque here: the server reads only its
``checksum``. Assignment and quota settings come in a small ``RuntimeConfig``
(JSON, stored with the publication)::

    {
      "surveyVersion": "3",                       # node_seed's survey_version string
      "saveMode": "every-page",                   # or "end-only" (runtime-design §5.0)
      "assignments": [
        {"variable": "framing", "levels": ["gain", "loss"], "method": "simple",
         "seedNode": "assign1/framing", "weights": [1, 1]},
        {"variable": "arm", "levels": ["a", "b", "c"], "method": "balanced",
         "seedNode": "assign1/arm"}
      ],
      "quotas": [{"node": "qc1", "quota": "women", "limit": 50}],
      "resumeExpiryDays": 30,                     # optional; see below
      "consent": {"version": "sha256:…", "countDeclines": false}   # optional
    }

``consent`` (optional, semantics.md §11): the survey has a consent page. The server then
refuses snapshots, quota checks and submits until the session has agreed to exactly this
``version``, stores no URL parameters, and on a decline deletes the session, keeping at
most an anonymous count (``countDeclines``).

``resumeExpiryDays`` (optional, a positive integer up to 3650) is how long a resume
link keeps working without activity (decision S-1). Absent: the server default
(``SessionPolicy.resume_expiry``, 30 days). Quota holds are released separately, after
24 h idle.

``seedNode`` is the ``node_id`` passed to ``osp_engine.random.node_seed``. The plan
compiler decides it, and the browser engine must use the same string. Several
``quotaCheck`` nodes may count against one ``quota``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from .errors import InvalidPayload

MAX_RESUME_EXPIRY_DAYS = 3650

SaveMode = Literal["every-page", "end-only"]
SAVE_MODES: tuple[SaveMode, ...] = ("every-page", "end-only")
Method = Literal["simple", "balanced"]


def _str(v: object, what: str, limit: int = 200) -> str:
    if not isinstance(v, str) or not v or len(v) > limit:
        raise InvalidPayload(f"{what} must be a string of 1-{limit} characters", "config.invalid")
    return v


@dataclass(frozen=True, slots=True)
class Assignment:
    variable: str
    levels: tuple[Any, ...]
    method: Method
    seed_node: str
    weights: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class QuotaNode:
    node: str
    quota: str
    limit: int


@dataclass(frozen=True, slots=True)
class ConsentConfig:
    version: str
    count_declines: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    survey_version: str
    save_mode: SaveMode = "every-page"
    assignments: tuple[Assignment, ...] = ()
    quotas: tuple[QuotaNode, ...] = ()
    resume_expiry_days: int | None = None
    consent: ConsentConfig | None = None

    @property
    def quota_by_node(self) -> dict[str, QuotaNode]:
        return {q.node: q for q in self.quotas}

    @property
    def quota_limits(self) -> dict[str, int]:
        return {q.quota: q.limit for q in self.quotas}

    @property
    def balanced(self) -> dict[str, tuple[Any, ...]]:
        return {a.variable: a.levels for a in self.assignments if a.method == "balanced"}

    @classmethod
    def from_json(cls, data: object) -> RuntimeConfig:
        if not isinstance(data, dict):
            raise InvalidPayload("config must be an object", "config.invalid")
        save_mode = data.get("saveMode", "every-page")
        if save_mode not in SAVE_MODES:
            raise InvalidPayload(f"saveMode must be one of {SAVE_MODES}", "config.invalid")
        assignments: list[Assignment] = []
        seen: set[str] = set()
        for a in data.get("assignments") or []:
            if not isinstance(a, dict):
                raise InvalidPayload("each assignment must be an object", "config.invalid")
            var = _str(a.get("variable"), "assignment variable")
            if var in seen:
                raise InvalidPayload(f"variable {var!r} is assigned twice", "config.invalid")
            seen.add(var)
            levels = a.get("levels")
            if not isinstance(levels, list) or not levels:
                raise InvalidPayload(f"{var!r} needs a non-empty levels list", "config.invalid")
            for lv in levels:
                if isinstance(lv, bool) or not isinstance(lv, str | int):
                    raise InvalidPayload(f"{var!r} levels must be strings or integers")
            if len({repr(lv) for lv in levels}) != len(levels):
                raise InvalidPayload(f"{var!r} has duplicate levels", "config.invalid")
            method = a.get("method", "simple")
            if method not in ("simple", "balanced"):
                raise InvalidPayload(f"{var!r} method must be simple or balanced")
            weights = a.get("weights")
            if weights is not None:
                if method == "balanced":
                    raise InvalidPayload(f"{var!r}: balanced assignment takes no weights")
                if (
                    not isinstance(weights, list)
                    or len(weights) != len(levels)
                    or any(
                        isinstance(w, bool)
                        or not isinstance(w, int | float)
                        or not math.isfinite(w)
                        or w < 0
                        for w in weights
                    )
                    or not any(w > 0 for w in weights)
                ):
                    raise InvalidPayload(
                        f"{var!r} weights must be one non-negative number per level"
                    )
                weights = tuple(weights)
            assignments.append(
                Assignment(var, tuple(levels), method, _str(a.get("seedNode"), "seedNode"), weights)
            )
        quotas: list[QuotaNode] = []
        limits: dict[str, int] = {}
        for q in data.get("quotas") or []:
            if not isinstance(q, dict):
                raise InvalidPayload("each quota must be an object", "config.invalid")
            node, quota, limit = (
                _str(q.get("node"), "quota node"),
                _str(q.get("quota"), "quota"),
                q.get("limit"),
            )
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                raise InvalidPayload(f"quota {quota!r} limit must be a non-negative integer")
            if limits.setdefault(quota, limit) != limit:
                raise InvalidPayload(f"quota {quota!r} has two different limits", "config.invalid")
            if any(x.node == node for x in quotas):
                raise InvalidPayload(f"quota node {node!r} is listed twice", "config.invalid")
            quotas.append(QuotaNode(node, quota, limit))
        expiry = data.get("resumeExpiryDays")
        if expiry is not None and (
            isinstance(expiry, bool)
            or not isinstance(expiry, int)
            or not 1 <= expiry <= MAX_RESUME_EXPIRY_DAYS
        ):
            raise InvalidPayload(
                f"resumeExpiryDays must be an integer from 1 to {MAX_RESUME_EXPIRY_DAYS}",
                "config.invalid",
            )
        consent = None
        raw = data.get("consent")
        if raw is not None:
            if not isinstance(raw, dict) or not isinstance(raw.get("countDeclines", False), bool):
                raise InvalidPayload(
                    "consent must be {version, countDeclines: bool}", "config.invalid"
                )
            consent = ConsentConfig(
                _str(raw.get("version"), "consent version", 80), raw.get("countDeclines", False)
            )
        return cls(
            _str(data.get("surveyVersion"), "surveyVersion"),
            save_mode,
            tuple(assignments),
            tuple(quotas),
            expiry,
            consent,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "surveyVersion": self.survey_version,
            "saveMode": self.save_mode,
            "assignments": [
                {
                    "variable": a.variable,
                    "levels": list(a.levels),
                    "method": a.method,
                    "seedNode": a.seed_node,
                    **({"weights": list(a.weights)} if a.weights is not None else {}),
                }
                for a in self.assignments
            ],
            "quotas": [{"node": q.node, "quota": q.quota, "limit": q.limit} for q in self.quotas],
            **(
                {"resumeExpiryDays": self.resume_expiry_days}
                if self.resume_expiry_days is not None
                else {}
            ),
            **(
                {
                    "consent": {
                        "version": self.consent.version,
                        "countDeclines": self.consent.count_declines,
                    }
                }
                if self.consent is not None
                else {}
            ),
        }
