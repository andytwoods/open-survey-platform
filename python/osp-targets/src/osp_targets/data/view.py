"""One response, read defensively: server row fields first, then the browser's record.

Nothing here trusts the shape of a stored record. A missing or odd field reads as ``None``
(an empty cell), never as an exception (AGENTS.md rule 3).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .layout import Layout, OrderInfo
from .model import SaveMode, StoredResponse

STATES = ("answered", "unanswered", "irrelevant", "not-reached")


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def iso_utc(value: Any) -> str | None:
    """A datetime (aware; naive is taken as UTC) or epoch milliseconds → ISO 8601 UTC with
    milliseconds, e.g. ``2026-10-16T09:30:00.000Z``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, int | float):
        try:
            dt = datetime.fromtimestamp(value / 1000, tz=UTC)
        except OverflowError, OSError, ValueError:
            return None
    else:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class ResponseView:
    def __init__(self, resp: StoredResponse, lay: Layout, save_mode: SaveMode | None) -> None:
        self.resp = resp
        self.lay = lay
        self.rec = _map(resp.record)
        answers = self.rec.get("answers")
        self.answers = _map(answers if isinstance(answers, Mapping) else resp.answers)
        self.save_mode = resp.save_mode or save_mode

    # -- meta ---------------------------------------------------------------------------

    def _first(self, *values: Any) -> Any:
        return next((v for v in values if v is not None), None)

    @property
    def allocation_mode(self) -> Any:
        if self.rec.get("allocation") == "seeded":  # semantics §7 (R1-8): engine drew one
            return "seeded"
        return self._first(self.resp.allocation_mode, self.rec.get("allocation"))

    def meta(self, column: str) -> Any:
        r, rec = self.resp, self.rec
        match column:
            case "_response_id":
                return r.response_id
            case "_session_id":
                return self._first(r.session_id, rec.get("sessionId"))
            case "_version":
                return self._first(r.version, self.lay.number, rec.get("surveyVersion"))
            case "_version_checksum":
                return self._first(r.version_checksum, self.lay.checksum)
            case "_plan_checksum":
                return rec.get("planChecksum")
            case "_engine_version":
                return self._first(r.engine_version, rec.get("engineVersion"))
            case "_allocation_mode":
                return self.allocation_mode
            case "_save_mode":
                return self.save_mode
            case "_seed":
                return self._first(r.session_seed, rec.get("sessionSeed"))
            case "_started_at":
                return iso_utc(r.started_at)
            case "_submitted_at":
                return iso_utc(r.submitted_at)
            case "_late":
                return bool(r.late)  # server-set (S-2); no flag means not late
            case "_after_close":
                return r.after_close
            case "_end":
                return rec.get("end")
            case "_language":
                return rec.get("language")
        return None

    def sort_key(self) -> tuple[str, str]:
        return (self.meta("_submitted_at") or "", self.resp.response_id)

    # -- variables ----------------------------------------------------------------------

    def condition(self, var_id: str) -> Any:
        """The condition in force: the record's ``conditions`` (all of them), else the
        server's assignment."""
        conditions = _map(self.rec.get("conditions"))
        if var_id in conditions:
            return conditions[var_id]
        return _map(self._first(self.resp.assigned, self.rec.get("assigned"))).get(var_id)

    def answer(self, qid: str) -> tuple[str | None, Any]:
        """(state, value). The value is only ever returned for ``answered`` (semantics §1);
        an unknown state reads as no state."""
        a = _map(self.answers.get(qid))
        state = a.get("state")
        if state not in STATES:
            return None, None
        return state, a.get("value") if state == "answered" else None

    def state(self, qid: str) -> str | None:
        return self.answer(qid)[0]

    def value(self, qid: str) -> Any:
        return self.answer(qid)[1]

    def multi_flag(self, qid: str, code: Any) -> int | None:
        state, value = self.answer(qid)
        if state != "answered":
            return None
        codes = {str(v) for v in value} if isinstance(value, list) else {str(value)}
        return 1 if str(code) in codes else 0

    def variable(self, var_id: str) -> Any:
        for key in ("embedded", "computed"):
            values = _map(self.rec.get(key))
            if var_id in values:
                return values[var_id]
        return None

    def variable_state(self, var_id: str) -> str | None:
        """An embedded or computed variable's state (semantics C3a-5, C2-6): the record's
        ``variableStates`` if it has one, else derived from its value and inputs."""
        state = _map(self.rec.get("variableStates")).get(var_id)
        if state in STATES:
            return state
        info = next((v for v in [*self.lay.embedded, *self.lay.computed] if v.id == var_id), None)
        if info is None:
            return None
        if self.variable(var_id) is not None:
            return "answered"
        if info.kind == "embedded":
            return "unanswered"
        inputs = [self.state(q) or "not-reached" for q in info.inputs]
        if inputs and all(s == "not-reached" for s in inputs):
            return "not-reached"
        if inputs and all(s in ("not-reached", "irrelevant") for s in inputs):
            return "irrelevant"
        return "unanswered"

    def orders(self) -> Mapping[str, Any]:
        return _map(self._first(self.rec.get("orders"), self.resp.orders))

    def order(self, o: OrderInfo) -> list[Any] | None:
        realised = _map(self.orders().get(o.kind)).get(o.node)
        return realised if isinstance(realised, list) else None
