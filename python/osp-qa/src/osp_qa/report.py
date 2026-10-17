"""Simulation report (task M1, review.md §7.1, §7.2). Pure: a runtime plan and an
``osp-sim/1`` result (from ``web/engine-sim``, run by ``osp_runtime.sim_sidecar``) in, a
JSON-ready ``osp-sim-report/1`` dict out.

- **Coverage** (which nodes, arms, ends, pages and questions were ever reached) comes from
  the exhaustive enumeration when there is one, else from the sample, and is labelled so.
  A sampled "never reached" is a hint, not a proof.
- **Balance**: chi-square goodness of fit of assigned conditions and realised randomiser
  orders against the design (uniform; assigned-variable ``weights`` if a plan has them),
  from the sample. With too few participants per order, the first position is tested.
- **Warnings**: unreachable nodes, never-taken branch arms, never-reached ends, required
  questions never shown, pages participants got stuck on, imbalance, runtime diagnostics.

Never raises on odd input: missing parts count as zero.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from math import perm
from typing import Any

from .stats import chi_square

REPORT_FORMAT = "osp-sim-report/1"
#: p below this flags an assignment or randomiser as imbalanced.
BALANCE_ALPHA = 0.001
#: Smallest expected count per category for the chi-square approximation.
MIN_EXPECTED = 5.0

Json = dict[str, Any]


def _map(x: Any) -> Mapping[str, Any]:
    return x if isinstance(x, Mapping) else {}


def _int(x: Any) -> int:
    return x if type(x) is int else 0


@dataclass(frozen=True)
class _Node:
    node: Mapping[str, Any]
    #: Enclosing container (branch or randomiser id), or None at top level.
    parent: str | None
    #: "then" / "else" when inside a branch.
    arm: str | None


def _flow(plan: Mapping[str, Any]) -> Iterator[_Node]:
    def walk(nodes: Any, parent: str | None, arm: str | None) -> Iterator[_Node]:
        for n in nodes if isinstance(nodes, list) else []:
            if not isinstance(n, Mapping) or not isinstance(n.get("id"), str):
                continue
            yield _Node(n, parent, arm)
            if n.get("type") == "branch":
                yield from walk(n.get("then"), n["id"], "then")
                yield from walk(n.get("else"), n["id"], "else")
            elif n.get("type") == "randomiser":
                yield from walk(n.get("children"), n["id"], None)

    yield from walk(plan.get("flow"), None, None)


def _warning(code: str, severity: str, target: str | None, message: str, certain: bool) -> Json:
    return {
        "code": code,
        "severity": severity,
        "target": target,
        "message": message,
        "certain": certain,
    }


def _balance_assignment(var: Mapping[str, Any], counts: Mapping[str, Any]) -> Json:
    levels = [str(level) for level in var.get("levels") or []]
    observed = [_int(counts.get(level)) for level in levels]
    total = sum(observed)
    weights = var.get("weights")
    if not (
        isinstance(weights, list)
        and len(weights) == len(levels)
        and all(isinstance(w, int | float) and w >= 0 for w in weights)
        and sum(weights) > 0
    ):
        weights = [1.0] * len(levels)
    expected = [total * w / sum(weights) for w in weights]
    out: Json = {
        "variable": var.get("id"),
        "reached": total,
        "observed": dict(zip(levels, observed, strict=True)),
        "expected": dict(zip(levels, expected, strict=True)),
        "test": None,
        "chiSquare": None,
        "df": None,
        "pValue": None,
        "maxDeviation": None,
        "balanced": None,
    }
    if total and min(expected, default=0) >= MIN_EXPECTED:
        cs = chi_square(observed, expected)
        if cs:
            out |= {
                "test": "levels",
                "chiSquare": cs.statistic,
                "df": cs.df,
                "pValue": cs.p_value,
                "maxDeviation": cs.max_deviation,
                "balanced": cs.p_value >= BALANCE_ALPHA,
            }
    return out


def _balance_randomiser(node: Mapping[str, Any], stats: Mapping[str, Any]) -> Json:
    children = [c.get("id") for c in node.get("children") or [] if isinstance(c, Mapping)]
    n = len(children)
    pick = node.get("pick")
    k = pick if type(pick) is int and 0 < pick <= n else n
    possible = perm(n, k) if n else 0
    reached = _int(stats.get("reached"))
    orders = {str(key): _int(v) for key, v in _map(stats.get("orders")).items()}
    positions = _map(stats.get("positions"))
    out: Json = {
        "id": node.get("id"),
        "reached": reached,
        "children": children,
        "pick": pick,
        "possibleOrders": possible,
        "observedOrders": len(orders),
        "orders": orders,
        "test": None,
        "expected": None,
        "chiSquare": None,
        "df": None,
        "pValue": None,
        "maxDeviation": None,
        "balanced": None,
    }
    if not reached or possible < 2:
        return out
    if reached / possible >= MIN_EXPECTED:
        # Every possible order is a category, including any never seen.
        e = reached / possible
        observed = list(orders.values()) + [0] * max(0, possible - len(orders))
        cs = chi_square(observed, [e] * len(observed))
        test = "orders"
    else:
        # Too many orders for the sample: which child comes first, each 1/n.
        e = reached / n
        first = [
            _int((positions.get(c) or [0])[0]) if isinstance(positions.get(c), list) else 0
            for c in children
        ]
        cs = chi_square(first, [e] * n) if e >= MIN_EXPECTED else None
        test = "first-position"
    if cs:
        out |= {
            "test": test,
            "expected": e,
            "chiSquare": cs.statistic,
            "df": cs.df,
            "pValue": cs.p_value,
            "maxDeviation": cs.max_deviation,
            "balanced": cs.p_value >= BALANCE_ALPHA,
        }
    return out


def build_report(plan: Mapping[str, Any], result: Mapping[str, Any]) -> Json:
    """The report for one simulation ``result`` of ``plan``."""
    plan = _map(plan)
    result = _map(result)
    sample = _map(result.get("sample"))
    exhaustive = result.get("exhaustive")
    certain = result.get("coverage") == "exhaustive" and isinstance(exhaustive, Mapping)
    cov = _map(exhaustive) if certain else sample
    options = _map(result.get("options"))
    space = _map(result.get("pathSpace"))
    runs = _int(sample.get("runs"))
    cov_runs = _int(cov.get("runs"))

    def never(what: str) -> str:
        return (
            f"{what} is unreachable: no enumerated path reaches it."
            if certain
            else f"{what} was never reached by {runs} simulated participants "
            "(sampled: it may still be reachable)."
        )

    warnings: list[Json] = []
    flow = list(_flow(plan))
    s_nodes, c_nodes = _map(sample.get("nodes")), _map(cov.get("nodes"))
    s_br, c_br = _map(sample.get("branches")), _map(cov.get("branches"))

    nodes: list[Json] = []
    ends: list[Json] = []
    branches: list[Json] = []
    reported_unreached: set[str] = set()
    for fn in flow:
        n = fn.node
        nid, ntype = n["id"], n.get("type")
        reached, covered = _int(s_nodes.get(nid)), _int(c_nodes.get(nid)) > 0
        nodes.append({"id": nid, "type": ntype, "reached": reached, "covered": covered})
        if ntype == "end":
            ends.append(
                {"id": nid, "outcome": n.get("outcome"), "reached": reached, "covered": covered}
            )
        if ntype == "branch":
            sb, cb = _map(s_br.get(nid)), _map(c_br.get(nid))
            row = {
                "id": nid,
                "reached": reached,
                "then": _int(sb.get("then")),
                "else": _int(sb.get("else")),
                "undetermined": _int(sb.get("undetermined")),
                "thenCovered": _int(cb.get("then")) > 0,
                "elseCovered": _int(cb.get("else")) > 0,
            }
            branches.append(row)
            if covered and not _int(cb.get("undetermined")):
                for arm, other in (("then", "else"), ("else", "then")):
                    if row[f"{arm}Covered"]:
                        continue
                    always = "true" if arm == "else" else "false"
                    if n.get(arm):
                        msg = (
                            f"The {arm} arm of branch {nid} is never taken on any enumerated "
                            f"path (its condition is always {always})."
                            if certain
                            else f"The {arm} arm of branch {nid} was never taken by {runs} "
                            "simulated participants (sampled: it may still be possible)."
                        )
                        warnings.append(
                            _warning(
                                "branch.arm_never_taken", "warning", f"{nid}.{arm}", msg, certain
                            )
                        )
                    else:
                        msg = (
                            f"Branch {nid} always takes its {other} arm: its condition is always "
                            f"{'true' if other == 'then' else 'false'}"
                            f"{' on every enumerated path' if certain else ' in the sample'}."
                        )
                        warnings.append(
                            _warning("branch.always_same_arm", "info", nid, msg, certain)
                        )
        if covered:
            continue
        # Report only the outermost unreached node: inside a reached container whose arm
        # (if any) was taken, or at top level.
        parent = fn.parent
        if parent is not None and (parent in reported_unreached or _int(c_nodes.get(parent)) == 0):
            reported_unreached.add(nid)
            continue
        if parent is not None and fn.arm and not _int(_map(c_br.get(parent)).get(fn.arm)):
            reported_unreached.add(nid)
            continue
        reported_unreached.add(nid)
        if ntype == "end":
            code, what = "end.never_reached", f"End {nid} (outcome {n.get('outcome')})"
        else:
            code, what = "node.unreachable", f"Flow node {nid} ({ntype})"
        warnings.append(_warning(code, "warning", nid, never(what), certain))

    pages_in = _map(plan.get("pages"))
    s_pages, c_pages = _map(sample.get("pages")), _map(cov.get("pages"))
    pages = [
        {
            "id": pid,
            "reached": _int(_map(s_pages.get(pid)).get("reached")),
            "shown": _int(_map(s_pages.get(pid)).get("shown")),
            "covered": _int(_map(c_pages.get(pid)).get("shown")) > 0,
        }
        for pid in pages_in
    ]

    items = _map(plan.get("items"))
    s_q, c_q = _map(sample.get("questions")), _map(cov.get("questions"))
    questions: list[Json] = []
    for qid in plan.get("questions") or []:
        item = _map(items.get(qid))
        states = {
            k: _int(_map(s_q.get(qid)).get(k))
            for k in ("answered", "unanswered", "irrelevant", "not-reached")
        }
        c = _map(c_q.get(qid))
        shown = _int(c.get("answered")) + _int(c.get("unanswered")) > 0
        required = item.get("required") is True
        questions.append({"id": qid, "required": required, "states": states, "shownCovered": shown})
        if required and not shown and cov_runs:
            msg = f"Required question {qid} is never shown " + (
                "on any enumerated path." if certain else f"to {runs} simulated participants."
            )
            warnings.append(_warning("question.required_never_shown", "warning", qid, msg, certain))

    for pid, count in _map(sample.get("stuck")).items():
        msg = (
            f"{_int(count)} of {runs} simulated participants could not get past page {pid}: "
            "no answer they tried passed its required/range/constraint checks."
        )
        warnings.append(_warning("participants.stuck", "error", pid, msg, False))
    if certain:
        for pid, count in _map(cov.get("stuck")).items():
            if pid in _map(sample.get("stuck")):
                continue
            msg = f"On {_int(count)} enumerated path(s) no answer passes the checks on page {pid}."
            warnings.append(_warning("participants.stuck", "error", pid, msg, True))

    variables = _map(plan.get("variables"))
    s_assign = _map(sample.get("assignments"))
    assignments = [
        _balance_assignment(v, _map(s_assign.get(vid)))
        for vid, v in variables.items()
        if isinstance(v, Mapping) and v.get("kind") == "assigned"
    ]
    s_rand = _map(sample.get("randomisers"))
    randomisers = [
        _balance_randomiser(fn.node, _map(s_rand.get(fn.node["id"])))
        for fn in flow
        if fn.node.get("type") == "randomiser"
    ]
    for row in assignments:
        if row["balanced"] is False:
            msg = (
                f"Assigned variable {row['variable']} is not balanced: chi-square "
                f"{row['chiSquare']:.1f} on {row['df']} df, p = {row['pValue']:.2g}."
            )
            warnings.append(
                _warning("assignment.imbalanced", "warning", row["variable"], msg, False)
            )
    for row in randomisers:
        if row["balanced"] is False:
            msg = (
                f"Randomiser {row['id']} orders are not balanced ({row['test']}): chi-square "
                f"{row['chiSquare']:.1f} on {row['df']} df, p = {row['pValue']:.2g}."
            )
            warnings.append(_warning("randomiser.imbalanced", "warning", row["id"], msg, False))

    quotas_plan = {fn.node["id"]: fn.node.get("quota") for fn in flow}
    quotas = [
        {
            "node": nid,
            "quota": quotas_plan.get(nid),
            "open": _int(_map(v).get("open")),
            "full": _int(_map(v).get("full")),
        }
        for nid, v in _map(sample.get("quotas")).items()
    ]

    diagnostics = {str(k): _int(v) for k, v in _map(sample.get("diagnostics")).items()}
    for key, count in diagnostics.items():
        code, _, site = key.partition(" ")
        msg = f"{count} simulated participant(s) hit runtime diagnostic {code} at {site}."
        warnings.append(_warning("runtime.diagnostic", "warning", site or None, msg, False))

    if not certain:
        reasons = [str(r) for r in space.get("reasons") or []]
        msg = "Coverage is sampled, not exhaustive" + (
            ": " + "; ".join(reasons) + "." if reasons else "."
        )
        warnings.append(_warning("coverage.sampled", "info", None, msg, False))

    order = {"error": 0, "warning": 1, "info": 2}
    warnings.sort(key=lambda w: order.get(w["severity"], 3))
    paths = _map(sample.get("paths"))
    return {
        "format": REPORT_FORMAT,
        "planChecksum": result.get("planChecksum"),
        "participants": runs,
        "seed": options.get("seed"),
        "answerStrategy": options.get("answerStrategy"),
        "quotaFull": options.get("quotaFull"),
        "coverage": "exhaustive" if certain else "sampled",
        "pathSpace": {
            "exhaustive": certain,
            "paths": space.get("paths") if certain else None,
            "combinations": space.get("combinations") if certain else None,
            "randomiserOrders": _int(space.get("randomiserOrders")),
            "assignmentCombinations": _int(space.get("assignmentCombinations")),
            "reasons": [str(r) for r in space.get("reasons") or []],
        },
        "pathsSeen": _int(paths.get("distinct")),
        "topPaths": [p for p in paths.get("top") or [] if isinstance(p, Mapping)],
        "outcomes": {str(k): _int(v) for k, v in _map(sample.get("outcomes")).items()},
        "stuck": {str(k): _int(v) for k, v in _map(sample.get("stuck")).items()},
        "nodes": nodes,
        "branches": branches,
        "ends": ends,
        "pages": pages,
        "questions": questions,
        "assignments": assignments,
        "randomisers": randomisers,
        "quotas": quotas,
        "diagnostics": diagnostics,
        "warnings": warnings,
    }
