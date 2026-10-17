# replay.py: recompute every response's realised orders and assignments from its seed.
#
# Part of an Open Survey Platform reproducibility package.
#
# MIT License
#
# Copyright (c) 2026 Open Survey Platform contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
# to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
# FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
"""Recompute realised orders and assignments from each response's seed and the plan.

    python3 replay/replay.py            # from the package root; Python 3.12+, stdlib only
    python3 replay/replay.py --json     # a machine-readable report

Every random decision (semantics §7) is ``randomize(items, node_seed(surveyVersion,
sessionSeed, nodeId))``, with the vendored ``osp_engine/random.py`` next to this script:

- a randomiser's block order: its children, shuffled, the first ``pick`` kept;
- a page's item order (``itemOrder: shuffle``), keyed by the page id;
- a question's choice order (``choiceOrder: shuffle``), keyed by the question id;
- each assigned variable: one uniform draw over its levels on the stream ``seedNode``.

Orders are recorded at first reach, so an order that was never reached (``null``) is not
checked. Exit code: 0 all match, 1 at least one mismatch, 2 the inputs can't be read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # the vendored osp_engine, also under `python -I`

from osp_engine.random import RandomInputError, assign, node_seed, randomize  # noqa: E402


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def plan_checksum(plan: dict) -> str:
    return "sha256:" + sha256_hex({k: v for k, v in plan.items() if k != "checksum"})


def randomisers(nodes: list, out: dict) -> dict:
    for n in nodes:
        if n.get("type") == "randomiser":
            out[n["id"]] = n
            randomisers(n.get("children", []), out)
        elif n.get("type") == "branch":
            randomisers(n.get("then", []), out)
            randomisers(n.get("else", []), out)
    return out


class Plan:
    def __init__(self, plan: dict, config: dict | None) -> None:
        self.raw = plan
        self.seed_version = plan["survey"]["seedVersion"]
        self.randomisers = randomisers(plan.get("flow", []), {})
        self.pages = plan.get("pages", {})
        self.items = plan.get("items", {})
        self.by_name = {item.get("name", iid): iid for iid, item in self.items.items()}
        self.variables = {
            v.get("name", vid): v
            for vid, v in plan.get("variables", {}).items()
            if v.get("kind") == "assigned"
        }
        methods = {}
        for a in (config or {}).get("assignments", []):
            methods[a.get("variable")] = a.get("method", "simple")
        self.methods = methods

    def expected_order(self, kind: str, key: str, seed: int) -> tuple[list | None, str]:
        """(expected order, note); None when the plan has no such random decision."""
        if kind == "blocks":
            node = self.randomisers.get(key)
            if node is None:
                return None, "no randomiser with this id in the plan"
            ids = [c["id"] for c in node.get("children", [])]
            order = randomize(ids, node_seed(self.seed_version, seed, key))
            pick = node.get("pick")
            return (order[:pick] if pick else order), ""
        if kind == "items":
            page = self.pages.get(key)
            if page is None or page.get("itemOrder") != "shuffle":
                return None, "no shuffled page with this id in the plan"
            return randomize(page.get("items", []), node_seed(self.seed_version, seed, key)), ""
        qid = self.by_name.get(key, key)
        item = self.items.get(qid)
        if item is None or item.get("choiceOrder") != "shuffle":
            return None, "no question with shuffled choices under this name in the plan"
        codes = [c["value"] for c in item.get("choices", [])]
        return randomize(codes, node_seed(self.seed_version, seed, qid)), ""

    def expected_condition(self, name: str, seed: int) -> object:
        v = self.variables[name]
        return assign(list(v["levels"]), None, node_seed(self.seed_version, seed, v["seedNode"]))


def check_response(plan: Plan, r: dict) -> dict:
    rid = r.get("responseId")
    out: dict = {"responseId": rid, "status": "match", "checks": 0, "mismatches": [], "notes": []}
    if r.get("allocationMode") == "limesurvey-native":
        out["status"] = "skipped"
        out["notes"].append("limesurvey-native allocation: LimeSurvey's own RNG decided")
        return out
    if r.get("planChecksum") not in (None, plan.raw.get("checksum")):
        out["mismatches"].append(
            {
                "what": "planChecksum",
                "stored": r.get("planChecksum"),
                "expected": plan.raw["checksum"],
            }
        )
    seed = r.get("seed")
    try:
        node_seed(plan.seed_version, seed, "check")
    except RandomInputError as exc:
        out["status"] = "mismatch"
        out["mismatches"].append({"what": "seed", "stored": seed, "expected": exc.message})
        return out
    orders = r.get("orders") or {}
    for kind in ("blocks", "items", "choices"):
        for key, stored in sorted((orders.get(kind) or {}).items()):
            if stored is None:  # never reached: nothing was realised
                continue
            expected, note = plan.expected_order(kind, key, seed)
            out["checks"] += 1
            if expected is None or canonical_json(expected) != canonical_json(stored):
                out["mismatches"].append(
                    {"what": f"orders.{kind}.{key}", "stored": stored, "expected": expected}
                    | ({"note": note} if note else {})
                )
    events = r.get("events") or []
    injected = events[0].get("assigned", {}) if events and isinstance(events[0], dict) else {}
    for name, stored in sorted((r.get("conditions") or {}).items()):
        if stored is None:
            continue
        if name not in plan.variables:
            out["mismatches"].append(
                {"what": f"conditions.{name}", "stored": stored, "expected": None}
            )
            continue
        var_id = plan.variables[name]["id"]
        if plan.methods.get(var_id, "simple") != "simple" and var_id in injected:
            out["notes"].append(f"conditions.{name}: balanced allocation, not seed-determined")
            continue
        expected = plan.expected_condition(name, seed)
        out["checks"] += 1
        if canonical_json(expected) != canonical_json(stored):
            out["mismatches"].append(
                {"what": f"conditions.{name}", "stored": stored, "expected": expected}
            )
    if out["mismatches"]:
        out["status"] = "mismatch"
    return out


def load(path: Path, what: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"replay.py: can't read {what} ({path}): {exc}") from None


def main(argv: list[str] | None = None) -> int:
    root = HERE.parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", type=Path, default=root / "survey" / "plan.json")
    ap.add_argument("--responses", type=Path, default=root / "data" / "responses.json")
    ap.add_argument("--config", type=Path, default=root / "survey" / "runtime-config.json")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    try:
        raw = load(args.plan, "the plan")
        config = load(args.config, "the runtime config") if args.config.is_file() else None
        report: dict = {"plan": {"checksum": raw.get("checksum")}, "responses": []}
        report["plan"]["checksumOk"] = plan_checksum(raw) == raw.get("checksum")
        plan = Plan(raw, config)
        if args.responses.is_file():
            data = load(args.responses, "the responses")
            for r in data.get("responses", []):
                report["responses"].append(check_response(plan, r))
        else:
            report["note"] = "no participant data in this package: nothing to replay"
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        print(f"replay.py: unexpected input: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    rs = report["responses"]
    counts = {s: sum(1 for r in rs if r["status"] == s) for s in ("match", "mismatch", "skipped")}
    report["summary"] = counts
    failed = counts["mismatch"] > 0 or not report["plan"]["checksumOk"]
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if failed else 0
    ok = "ok" if report["plan"]["checksumOk"] else "MISMATCH"
    print(f"plan {raw.get('checksum')}: checksum {ok}")
    if "note" in report:
        print(report["note"])
    for r in rs:
        line = f"{r['responseId']}: {r['status']} ({r['checks']} checks)"
        print(line.replace("mismatch", "MISMATCH"))
        for m in r["mismatches"]:
            print(
                f"  {m['what']}: stored {json.dumps(m['stored'], ensure_ascii=False)}, "
                f"expected {json.dumps(m['expected'], ensure_ascii=False)}"
            )
        for n in r["notes"]:
            print(f"  note: {n}")
    print(f"{counts['match']} match, {counts['mismatch']} mismatch, {counts['skipped']} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
