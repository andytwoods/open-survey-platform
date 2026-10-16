"""Retention policy and the pure planner that decides what to delete.

``plan_retention`` does no I/O and reads no clock: the executor
(``Store.run_retention``) gathers facts, passes ``now`` in, and deletes what the
plan names. A policy is per survey and covers every participant row of every
version of that survey: responses *and* sessions (sessions hold autosaved
instances, so they are participant data too).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from .errors import InvalidInput

RetentionKind = Literal["none", "days_after_close", "after_date"]


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    kind: RetentionKind = "none"
    days: int | None = None  # for days_after_close
    until: datetime | None = None  # for after_date (timezone-aware)

    @classmethod
    def none(cls) -> RetentionPolicy:
        return cls("none")

    @classmethod
    def days_after_close(cls, days: int) -> RetentionPolicy:
        return cls("days_after_close", days=days)

    @classmethod
    def after_date(cls, until: datetime) -> RetentionPolicy:
        return cls("after_date", until=until)

    def validate(self) -> RetentionPolicy:
        if self.kind == "none":
            if self.days is not None or self.until is not None:
                raise InvalidInput("policy 'none' takes no days/until")
        elif self.kind == "days_after_close":
            if type(self.days) is not int or self.days < 0 or self.until is not None:
                raise InvalidInput("days_after_close needs a non-negative integer `days`")
        elif self.kind == "after_date":
            if not isinstance(self.until, datetime) or self.until.tzinfo is None:
                raise InvalidInput("after_date needs a timezone-aware `until`")
            if self.days is not None:
                raise InvalidInput("after_date takes no `days`")
        else:
            raise InvalidInput(f"unknown retention kind {self.kind!r}")
        return self


def deletion_due_at(policy: RetentionPolicy, closed_at: datetime | None) -> datetime | None:
    """When participant data for the survey becomes due for deletion (None: never/not yet)."""
    if policy.kind == "days_after_close":
        if closed_at is None or policy.days is None:
            return None  # an open survey is never purged by a days-after-close policy
        return closed_at + timedelta(days=policy.days)
    if policy.kind == "after_date":
        return policy.until
    return None


@dataclass(frozen=True, slots=True)
class SurveyFacts:
    tenant_id: str
    survey_id: str
    policy: RetentionPolicy
    closed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ParticipantRow:
    kind: Literal["response", "session"]
    row_id: str
    tenant_id: str
    survey_id: str


@dataclass(frozen=True, slots=True)
class SurveyPurge:
    tenant_id: str
    survey_id: str
    due_at: datetime
    response_ids: tuple[str, ...]
    session_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    now: datetime
    purges: tuple[SurveyPurge, ...] = field(default_factory=tuple)

    @property
    def response_ids(self) -> tuple[str, ...]:
        return tuple(r for p in self.purges for r in p.response_ids)

    @property
    def session_ids(self) -> tuple[str, ...]:
        return tuple(s for p in self.purges for s in p.session_ids)


def plan_retention(
    surveys: Iterable[SurveyFacts], rows: Iterable[ParticipantRow], now: datetime
) -> RetentionPlan:
    """Pick every participant row whose survey's deletion time is at or before ``now``.

    Rows are matched on ``(tenant_id, survey_id)``, never on survey id alone.
    Surveys with nothing left to delete are omitted, so re-running is a no-op.
    """
    if now.tzinfo is None:
        raise InvalidInput("now must be timezone-aware")
    due: dict[tuple[str, str], datetime] = {}
    for s in surveys:
        at = deletion_due_at(s.policy, s.closed_at)
        if at is not None and at <= now:
            due[(s.tenant_id, s.survey_id)] = at
    picked: dict[tuple[str, str], tuple[list[str], list[str]]] = {k: ([], []) for k in due}
    for r in rows:
        bucket = picked.get((r.tenant_id, r.survey_id))
        if bucket is not None:
            (bucket[0] if r.kind == "response" else bucket[1]).append(r.row_id)
    purges = tuple(
        SurveyPurge(t, s, due[(t, s)], tuple(sorted(resp)), tuple(sorted(sess)))
        for (t, s), (resp, sess) in sorted(picked.items())
        if resp or sess
    )
    return RetentionPlan(now=now, purges=purges)
