"""Python -> TypeScript parity vectors for @osp/ops, into web/ops/.build/ (gitignored).

    uv run python web/ops/scripts/build_vectors.py [--force]

`osp-ops` (Python) runs every op on every fixture and on seeded random op sequences, and
writes what it did; web/ops/test/parity.test.ts replays the same inputs through the
TypeScript port and asserts byte-identical canonical JSON for every result.

Files (all JSON):

- `fields.json`   op ids/labels/areas and the `model_fields` lists `set_property` uses.
- `models.json`   pydantic vectors: hostile and valid inputs for every params model and for
                  `Ending`, `RedirectTemplate`, `Source`, `Hooks`, `Theme`, the expression
                  AST; the dump or the full error list (type, loc, msg).
- `py.json`       `repr`, `str.strip`, `str.splitlines`, `Decimal` str and `float` repr.
- `tests.json`    every `run` / `invoke` / `apply_transaction` call the osp-ops test suite
                  makes (hand-written cases and the seeded Hypothesis fuzzers), with its result.
- `single.json`   op x fixture: every op on every fixture survey (and the ops tests' base
                  survey with the guard's EXAMPLES), hostile params and hostile surveys.
- `sequences.json` seeded random sequences of runs and transactions (hundreds of
                  sequences, tens of steps, invalid ops among them), with undo and redo.
- `oracle.json`   the validator's answers: what `osp_spec.parse` / `validate` /
                  `bank.check_fragment` / `osp_expr.parse` returned for each input the ops
                  asked about (keyed by the SHA-256 of its canonical JSON).

The survey validator is not part of the port (CE4), so the TS ops take it injected. The
vectors record its outcome for every document the Python ops validated; the TS test
injects an oracle that answers from that table, and fails on any document Python never
asked about (so a TS op that builds a different document is caught twice).

Documents are compared by the SHA-256 of their JSON in their own key order (`json.dumps(
separators=(",", ":"), ensure_ascii=False)`, what `JSON.stringify` writes), so a key order
difference is a difference; every other result is compared as JSON in key order too.
JavaScript has no int/float distinction, so integral floats are written as ints before
hashing (`2.0` -> `2`); see web/ops/README.md.

A stamp of the inputs (this script, osp-ops, osp-spec, osp-expr sources, fixtures) lets a
second run with nothing changed return at once.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "web" / "ops" / ".build"
TESTS = ROOT / "python" / "osp-ops" / "tests"
FIXTURES = ROOT / "fixtures"
N_SEQUENCES = 400
STEPS = (15, 45)

sys.path.insert(0, str(TESTS))


# --- canonical JSON and the oracle ------------------------------------------------------------


def _ints(v: Any) -> Any:
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, dict):
        return {k: _ints(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_ints(x) for x in v]
    return v


def canon(v: Any) -> str:
    return json.dumps(_ints(v), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def ordered(v: Any) -> str:
    """JSON in the document's own key order (what `JSON.stringify` gives in TS)."""
    return json.dumps(_ints(v), separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def h(v: Any) -> str:
    """Documents are compared in their own key order: the same keys in another order are
    another document (patches, diagnostics and exports follow key order)."""
    return hashlib.sha256(ordered(v).encode("utf-8")).hexdigest()


ORACLE: dict[str, dict[str, Any]] = {"parse": {}, "fragment": {}, "expr": {}}


def _diags(ds: Any) -> list[dict[str, Any]]:
    return [d.model_dump(mode="json") for d in ds]


def install_recorders() -> None:
    """Wrap every validator entry point the ops call, so each answer is recorded."""
    import osp_expr
    import osp_ops.bank_ops as bank_ops
    import osp_ops.question_type_ops as qt_ops
    import osp_ops.registry as registry
    import osp_ops.transaction as transaction
    from osp_spec import parse as real_parse
    from osp_spec.bank import check_fragment as real_check

    def parse(doc: Any) -> Any:
        res = real_parse(doc)
        try:
            ORACLE["parse"][h(doc)] = {"valid": res[0] is not None, "diagnostics": _diags(res[1])}
        except (TypeError, ValueError):
            pass  # not JSON (never sent by the vectors)
        return res

    def validate(doc: Any) -> Any:
        return parse(doc)[1]

    def check_fragment(fragment: Any) -> Any:
        res = real_check(fragment)
        ORACLE["fragment"][h(fragment)] = _diags(res)
        return res

    real_expr_parse = osp_expr.parse

    def expr_parse(text: str) -> Any:
        res = real_expr_parse(text)
        if res.expr is None:
            out: dict[str, Any] = {
                "expr": None,
                "diagnostics": [
                    {"code": d.code, "message": d.message, "start": d.start, "end": d.end}
                    for d in res.diagnostics
                ],
            }
        else:
            out = {"expr": osp_expr.EXPR_ADAPTER.dump_python(res.expr, mode="json")}
        ORACLE["expr"][text] = out
        return res

    registry.parse = parse
    transaction.parse = parse
    qt_ops.validate = validate
    bank_ops.check_fragment = check_fragment
    osp_expr.parse = expr_parse


# --- results as JSON ------------------------------------------------------------------------------


def op_result(res: Any) -> dict[str, Any]:
    return {
        "ok": res.ok,
        "survey": h(res.survey),
        "inverse": None if res.inverse is None else res.inverse.model_dump(mode="json"),
        "patch": res.patch,
        "diagnostics": _diags(res.diagnostics),
    }


def tx_result(res: Any) -> dict[str, Any]:
    return {
        "status": res.status,
        "survey": h(res.draft.survey),
        "revision": res.draft.revision,
        "inverse": [i.model_dump(mode="json") for i in res.inverse],
        "patch": res.patch,
        "diagnostics": _diags(res.diagnostics),
        "failedIndex": res.failed_index,
    }


# --- what a survey holds (for picking plausible targets) -------------------------------------------


class Facts:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.doc = doc
        self.questions: list[dict[str, Any]] = []
        self.pages: list[str] = []
        self.blocks: list[str] = []
        self.page_block: dict[str, str] = {}
        for b in doc.get("blocks") or []:
            self.blocks.append(b["id"])
            for p in b["pages"]:
                self.pages.append(p["id"])
                self.page_block[p["id"]] = b["id"]
                for q in p["items"]:
                    self.questions.append(q)
        self.qids = [q["id"] for q in self.questions]
        self.lists = [cl["id"] for cl in doc.get("choiceLists") or []]
        self.variables = doc.get("variables") or []
        self.vids = [v["id"] for v in self.variables]
        self.quotas = [q["id"] for q in doc.get("quotas") or []]
        self.nodes: list[dict[str, Any]] = []

        def walk(ns: list[Any]) -> None:
            for n in ns:
                self.nodes.append(n)
                if n.get("type") == "branch":
                    walk(n.get("then", []))
                    walk(n.get("else", []))
                elif n.get("type") == "randomiser":
                    walk(n.get("children", []))

        walk(doc.get("flow") or [])
        self.nids = [n["id"] for n in self.nodes]
        self.langs = (doc.get("metadata") or {}).get("languages") or ["en"]
        self.owners = self.lists + [
            q["id"] for q in self.questions if q.get("type") in ("single", "multi", "matrix")
        ]
        self.matrices = [q for q in self.questions if q.get("type") == "matrix"]
        self.all_ids = self.qids + self.pages + self.blocks + self.lists + self.vids
        self.all_ids += self.quotas + self.nids

    def choices_of(self, owner: str) -> list[Any]:
        for cl in self.doc.get("choiceLists") or []:
            if cl["id"] == owner:
                return cl["choices"]
        for q in self.questions:
            if q["id"] == owner:
                return q.get("choices") or []
        return []


QTYPES = ["integer", "decimal", "text", "single", "multi", "date", "matrix", "slider", "note"]
BAD_IDS = ["nope", "1bad", "and", "id", "_x", "a" * 70, "x y", "é", "", "it's", 'say "hi"', "😀x", "tab\tid", "nl\n", "Q1", "seed"]
HOSTILE = [None, True, False, 0, -1, 7, "x", "", [], {}, [1], {"a": 1}, 2.5]


class Gen:
    """Plausible (and sometimes hostile) params for every op, from the current survey."""

    def __init__(self, r: random.Random, hostility: float = 1.0) -> None:
        self.r = r
        self.n = 0
        self.hostility = hostility

    def pick(self, xs: list[Any], wrong: float = 0.08) -> Any:
        if not xs or self.r.random() < wrong * self.hostility:
            return self.r.choice(BAD_IDS + (xs[:1] if xs else []))
        return self.r.choice(xs)

    def fresh(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n}_{self.r.randint(0, 99)}"

    def maybe(self, p: float = 0.5) -> bool:
        return self.r.random() < p

    def index(self, n: int | None = None) -> Any:
        roll = self.r.random()
        if roll < 0.45:
            return None
        if roll < 0.9:
            return self.r.randint(0, max(0, n if n is not None else 3))
        return self.r.choice([n + 5 if n is not None else 99, -1])

    def label(self, f: Facts) -> Any:
        roll = self.r.random()
        if roll < 0.45:
            return self.r.choice(["Label", "How old are you?", "Why ${%s}?" % self.pick(f.qids), " "])
        if roll < 0.7 and len(f.langs) > 1:
            return {lang: f"T {lang}" for lang in f.langs}
        if roll < 0.8:
            return {"type": "rich", "blocks": [{"type": "p", "content": [{"text": "Hi "}, {"pipe": self.pick(f.qids)}]}]}
        if roll < 0.9:
            return {"type": "rich", "blocks": [{"type": "p", "content": [{"text": "Bold", "marks": ["b"]}]}]}
        return self.r.choice([{"xx": "bad"}, {"type": "rich", "blocks": [{"type": "h", "level": 1, "content": [{"text": "H"}]}]}, "x" * 600])

    def expr(self, f: Facts, depth: int = 2) -> Any:
        refs = f.qids + f.vids
        if depth <= 0 or self.maybe(0.3):
            roll = self.r.random()
            if roll < 0.5:
                return {"kind": "ref", "id": self.pick(refs, 0.05)}
            if roll < 0.75:
                return {"kind": "int", "value": self.r.randint(-2, 5)}
            if roll < 0.85:
                return {"kind": "text", "value": self.r.choice(["a", "b", "gain"])}
            if roll < 0.92:
                return {"kind": "decimal", "value": self.r.choice(["2.5", "0.10", "1E+3", 1.5, " 7 "])}
            return {"kind": "bool", "value": True}
        roll = self.r.random()
        ref = {"kind": "ref", "id": self.pick(refs, 0.05)}
        if roll < 0.35:
            return {"kind": "compare", "op": self.r.choice(["==", "!=", ">=", "<"]), "left": ref, "right": self.expr(f, depth - 1)}
        if roll < 0.5:
            return {"kind": self.r.choice(["and", "or"]), "args": [self.expr(f, depth - 1) for _ in range(2)]}
        if roll < 0.6:
            return {"kind": "answered", "ref": ref}
        if roll < 0.7:
            return {"kind": "contains", "ref": ref, "value": {"kind": "int", "value": self.r.randint(0, 3)}}
        if roll < 0.78:
            return {"kind": "not", "arg": self.expr(f, depth - 1)}
        if roll < 0.85:
            return {"kind": "if", "cond": self.expr(f, depth - 1), "then": ref, "else": {"kind": "null"}}
        if roll < 0.92:
            return {"kind": "arith", "op": "+", "left": ref, "right": {"kind": "int", "value": 1}}
        return self.r.choice([{"kind": "bogus"}, {"kind": "and", "args": [ref]}, {"kind": "ref", "id": "and"}, {"op": "=="}, 5])

    def condition(self, f: Facts) -> Any:
        roll = self.r.random()
        if roll < 0.55:
            return self.expr(f)
        if roll < 0.85:
            q = self.pick(f.qids)
            return self.r.choice([f"{q} >= 18", f"answered({q})", f"{q} == 1 and answered({q})", f"contains({q}, 2)", "1 +", "((", f"{q} > 2.5"])
        return self.r.choice([None, "", "  "])

    def node(self, f: Facts) -> Any:
        roll = self.r.random()
        nid = {"id": self.fresh("n")} if self.maybe(0.4) else {}
        if roll < 0.35:
            return {"type": "block", **nid, "block": self.pick(f.blocks)}
        if roll < 0.5:
            return {"type": "end", **nid, "outcome": self.r.choice(["complete", "screened_out", "bad-x"])}
        if roll < 0.62:
            return {"type": "branch", **nid, "if": self.expr(f, 1), "then": []}
        if roll < 0.72:
            return {"type": "randomiser", **nid, "children": [{"type": "end", "id": self.fresh("e")}]}
        if roll < 0.8:
            assigned = [v["id"] for v in f.variables if v.get("kind") == "assigned"]
            return {"type": "assign", **nid, "variables": [self.pick(assigned)]}
        if roll < 0.88:
            return {"type": "quotaCheck", **nid, "quota": self.pick(f.quotas)}
        return self.r.choice([{"type": "bogus"}, {"block": "b"}, {"type": "end", "id": self.pick(f.all_ids)}])

    def value_for(self, prop: str, f: Facts) -> Any:
        table: dict[str, list[Any]] = {
            "required": [True, False, "yes"],
            "help": ["Some help", {"en": "Help"}, None],
            "label": [self.label(f)],
            "title": ["Title", {"en": "T"}, None, 5],
            "name": ["v_" + self.fresh("n"), "1bad", self.pick(f.qids)],
            "min": [0, 1, "2.5", -3, "x"],
            "max": [10, 100, "7.25", "y"],
            "step": [1, 5, 0],
            "multiline": [True, False],
            "choiceOrder": ["shuffle", "fixed", "random"],
            "itemOrder": ["shuffle", "fixed"],
            "backNavigation": [False, True],
            "saveMode": ["end-only", "every-page", "never"],
            "resumeExpiryDays": [7, 0],
            "license": ["CC0-1.0", 3],
            "description": ["About", {"type": "rich", "blocks": []}],
            "pick": [1, 0, 2],
            "outcome": ["complete", "screened_out"],
            "limit": [5, -1],
            "valueType": ["decimal", "integer", "text"],
            "param": ["src", 5],
            "default": ["x", 3],
            "levels": [["a", "b"], []],
            "choices": [[{"value": 1, "label": "A"}, {"value": 2, "label": "B"}], []],
            "choiceList": [self.pick(f.lists)],
            "showIf": [self.expr(f, 1)],
            "constraintMessage": ["Too big"],
        }
        return self.r.choice(table.get(prop, HOSTILE))

    # -- params per op --------------------------------------------------------------------------

    def params(self, op_id: str, f: Facts) -> Any:
        r = self.r
        fn = getattr(self, "p_" + op_id)
        p = fn(f)
        if r.random() < 0.12 * self.hostility:
            p = self.hostile(op_id, p)
        return p

    def hostile(self, op_id: str, p: Any) -> Any:
        r = self.r
        roll = r.random()
        if roll < 0.08:
            return r.choice([None, [], 5, "x"])
        p = dict(p)
        if roll < 0.35 and p:
            del p[r.choice(list(p))]
        elif roll < 0.55:
            p[r.choice(["extra", "zz"])] = 1
        elif p:
            p[r.choice(list(p))] = r.choice(HOSTILE)
        return p

    def p_add_question(self, f: Facts) -> Any:
        p: dict[str, Any] = {"page": self.pick(f.pages)}
        if self.maybe(0.7):
            p["type"] = self.r.choice(QTYPES)
        if self.maybe(0.4):
            p["index"] = self.index(3)
        if self.maybe(0.4):
            p["id"] = self.r.choice([self.fresh("q"), self.pick(f.all_ids), "1bad", "ab\n"])
        if self.maybe(0.4):
            p["label"] = self.label(f)
        if self.maybe(0.15):
            q: dict[str, Any] = {"type": self.r.choice(["note", "text", "integer"]), "label": self.label(f)}
            if self.maybe(0.3):
                q["id"] = self.r.choice([self.fresh("qq"), self.pick(f.qids)])
            p["question"] = q
        if self.maybe(0.15):
            p["defaults"] = self.r.choice(
                [{"required": True}, {"custom.weight": 1, "custom.construct": "x"}, {"type": "text"}, {"a.b": 1}, {}, {"help": "H"}]
            )
        return p

    def p_delete_question(self, f: Facts) -> Any:
        return {"id": self.pick(f.qids), "cascade": self.maybe(0.4), "force": self.maybe(0.2)}

    def p_duplicate_question(self, f: Facts) -> Any:
        p = {"id": self.pick(f.qids)}
        if self.maybe(0.3):
            p["new_id"] = self.r.choice([self.fresh("d"), self.pick(f.all_ids), "9x"])
        return p

    def p_move_question(self, f: Facts) -> Any:
        return {"id": self.pick(f.qids), "page": self.pick(f.pages), "index": self.index(3)}

    def p_change_question_type(self, f: Facts) -> Any:
        q = self.pick(f.questions, 0.0) if f.questions else {"id": "nope"}
        p: dict[str, Any] = {"id": q.get("id", "nope") if isinstance(q, dict) else "nope", "type": self.r.choice(QTYPES)}
        if self.maybe(0.3):
            p["force"] = True
        if self.maybe(0.08) and isinstance(q, dict):
            p["question"] = {**q, "type": p["type"]}
        return p

    def p_set_property(self, f: Facts) -> Any:
        target = self.r.choice(
            [self.pick(f.qids), self.pick(f.pages), self.pick(f.blocks), self.pick(f.nids), self.pick(f.vids),
             self.pick(f.quotas), self.pick(f.lists), "/metadata", "/settings", "nope"]
        )
        prop = self.r.choice(
            ["required", "help", "label", "title", "name", "min", "max", "step", "multiline", "choiceOrder",
             "itemOrder", "backNavigation", "saveMode", "resumeExpiryDays", "license", "description", "pick",
             "outcome", "limit", "valueType", "param", "default", "levels", "choices", "choiceList", "showIf",
             "constraint", "constraintMessage", "id", "type", "custom", "source", "instruments", "items", "bogus"]
        )
        fields = self.fields_of(target, f)
        if fields and self.maybe(0.7):
            prop = self.r.choice(fields)
        p: dict[str, Any] = {"target": target, "property": prop}
        if self.maybe(0.2):
            p["unset"] = True
        else:
            p["value"] = self.value_for(prop, f)
        return p

    def fields_of(self, target: str, f: Facts) -> list[str]:
        from osp_ops.property_ops import (
            FIXED_CLASSES,
            NODE_CLASSES,
            QUESTION_CLASSES,
            SINGLETONS,
            VARIABLE_CLASSES,
            model_fields,
        )

        if target in SINGLETONS:
            return model_fields(SINGLETONS[target][1])
        for q in f.questions:
            if q["id"] == target and q.get("type") in QUESTION_CLASSES:
                return model_fields(QUESTION_CLASSES[q["type"]])
        for n in f.nodes:
            if n["id"] == target and n.get("type") in NODE_CLASSES:
                return model_fields(NODE_CLASSES[n["type"]])
        for v in f.variables:
            if v["id"] == target and v.get("kind") in VARIABLE_CLASSES:
                return model_fields(VARIABLE_CLASSES[v["kind"]])
        for kind, ids in (("page", f.pages), ("block", f.blocks), ("choiceList", f.lists), ("quota", f.quotas)):
            if target in ids:
                return model_fields(FIXED_CLASSES[kind])
        return []

    def p_set_custom_property(self, f: Facts) -> Any:
        p: dict[str, Any] = {"target": self.pick(f.qids), "key": self.r.choice(["construct", "weight", "n", "Bad Key", "a" * 41])}
        if self.maybe(0.25):
            p["unset"] = True
        else:
            p["value"] = self.r.choice(["demographics", 2.5, 1, True, None, "x"])
        return p

    def p_add_page(self, f: Facts) -> Any:
        p: dict[str, Any] = {"block": self.pick(f.blocks)}
        if self.maybe(0.3):
            p["index"] = self.index(2)
        if self.maybe(0.3):
            p["id"] = self.r.choice([self.fresh("p"), self.pick(f.all_ids)])
        if self.maybe(0.3):
            p["question_type"] = self.r.choice(QTYPES)
        if self.maybe(0.1):
            p["page"] = {"items": [{"id": self.fresh("pq"), "type": "note", "label": "N"}]}
        return p

    def p_delete_page(self, f: Facts) -> Any:
        return {"id": self.pick(f.pages), "cascade": self.maybe(0.4), "force": self.maybe(0.2)}

    def p_rename_page(self, f: Facts) -> Any:
        return {"id": self.pick(f.pages), "new_id": self.r.choice([self.fresh("pr"), self.pick(f.all_ids), "bad id"])}

    def p_move_page(self, f: Facts) -> Any:
        return {"id": self.pick(f.pages), "block": self.pick(f.blocks), "index": self.index(2)}

    def p_add_block(self, f: Facts) -> Any:
        p: dict[str, Any] = {}
        if self.maybe(0.3):
            p["index"] = self.index(2)
        if self.maybe(0.3):
            p["id"] = self.r.choice([self.fresh("b"), self.pick(f.all_ids)])
        if self.maybe(0.3):
            p["title"] = self.r.choice(["New", ""])
        if self.maybe(0.2):
            p["question_type"] = self.r.choice(QTYPES)
        if self.maybe(0.08):
            p["block"] = {"pages": [{"id": self.fresh("bp"), "items": [{"id": self.fresh("bq"), "type": "text", "label": "T"}]}]}
        return p

    def p_delete_block(self, f: Facts) -> Any:
        return {"id": self.pick(f.blocks), "cascade": self.maybe(0.5), "force": self.maybe(0.2)}

    def p_rename_block(self, f: Facts) -> Any:
        return {"id": self.pick(f.blocks), "title": self.r.choice(["Main", None, "x"])}

    def p_move_block(self, f: Facts) -> Any:
        return {"id": self.pick(f.blocks), "index": self.r.randint(0, len(f.blocks) + 1)}

    def p_duplicate_page(self, f: Facts) -> Any:
        p = {"id": self.pick(f.pages)}
        if self.maybe(0.3):
            p["new_id"] = self.r.choice([self.fresh("dp"), self.pick(f.all_ids)])
        return p

    def p_duplicate_block(self, f: Facts) -> Any:
        p = {"id": self.pick(f.blocks)}
        if self.maybe(0.3):
            p["new_id"] = self.r.choice([self.fresh("db"), self.pick(f.all_ids)])
        return p

    def _code(self, f: Facts, owner: str) -> Any:
        codes = [c.get("value") for c in f.choices_of(owner)]
        return self.r.choice(codes + [99, "zz"]) if codes and self.maybe(0.85) else self.r.choice([1, "a", 99])

    def p_add_choice(self, f: Facts) -> Any:
        owner = self.pick(f.owners)
        p: dict[str, Any] = {"owner": owner}
        if self.maybe(0.7):
            p["label"] = self.label(f)
        if self.maybe(0.4):
            p["value"] = self.r.choice([self._code(f, owner), 42, "new", -3])
        if self.maybe(0.3):
            p["index"] = self.index(3)
        return p

    def p_delete_choice(self, f: Facts) -> Any:
        owner = self.pick(f.owners)
        return {"owner": owner, "value": self._code(f, owner), "cascade": self.maybe(0.4), "force": self.maybe(0.2)}

    def p_move_choice(self, f: Facts) -> Any:
        owner = self.pick(f.owners)
        return {"owner": owner, "value": self._code(f, owner), "index": self.r.randint(0, 4)}

    def p_set_choice(self, f: Facts) -> Any:
        owner = self.pick(f.owners)
        p: dict[str, Any] = {"owner": owner, "value": self._code(f, owner)}
        if self.maybe(0.5):
            p["new_value"] = self.r.choice([self._code(f, owner), 77, "q"])
        if self.maybe(0.6):
            p["label"] = self.label(f)
        if self.maybe(0.3):
            p["force"] = True
        return p

    def p_bulk_paste_choices(self, f: Facts) -> Any:
        lines = self.r.choice(
            ["One\nTwo\n\nThree", "Kiwi\nx\tMango", "1\tYes\n0\tNo", "  \n\t\n", "5\tA\n5\tB", "a\r\nb\x0bc d", " 7 \t Seven \nEight"]
        )
        p: dict[str, Any] = {"owner": self.pick(f.owners), "text": lines}
        if self.maybe(0.5):
            p["mode"] = self.r.choice(["replace", "append"])
        if self.maybe(0.3):
            p["force"] = True
        return p

    def _matrix(self, f: Facts) -> Any:
        if f.matrices and self.maybe(0.85):
            return self.r.choice(f.matrices)
        return {"id": self.pick(f.qids), "rows": []}

    def _row(self, m: Any) -> str:
        rows = [r["id"] for r in m.get("rows") or []]
        return self.r.choice(rows) if rows and self.maybe(0.9) else "zz"

    def p_add_matrix_row(self, f: Facts) -> Any:
        m = self._matrix(f)
        p: dict[str, Any] = {"question": m["id"]}
        if self.maybe(0.4):
            p["id"] = self.r.choice([self.fresh("r"), self._row(m), "bad row", "and"])
        if self.maybe(0.6):
            p["label"] = self.label(f)
        if self.maybe(0.3):
            p["required"] = self.r.choice([True, False, None])
        if self.maybe(0.3):
            p["index"] = self.index(3)
        return p

    def p_delete_matrix_row(self, f: Facts) -> Any:
        m = self._matrix(f)
        return {"question": m["id"], "row": self._row(m), "cascade": self.maybe(0.4), "force": self.maybe(0.2)}

    def p_move_matrix_row(self, f: Facts) -> Any:
        m = self._matrix(f)
        return {"question": m["id"], "row": self._row(m), "index": self.r.randint(0, 3)}

    def p_rename_matrix_row(self, f: Facts) -> Any:
        m = self._matrix(f)
        return {"question": m["id"], "row": self._row(m), "label": self.label(f)}

    def p_set_matrix_row_required(self, f: Facts) -> Any:
        m = self._matrix(f)
        return {"question": m["id"], "row": self._row(m), "required": self.r.choice([True, False, None])}

    def p_create_choice_list(self, f: Facts) -> Any:
        p: dict[str, Any] = {}
        if self.maybe(0.5):
            p["id"] = self.r.choice([self.fresh("list"), self.pick(f.all_ids)])
        if self.maybe(0.5):
            p["choices"] = self.r.choice([[{"value": 1, "label": "A"}], [{"value": "x", "label": "X"}, {"value": "y", "label": "Y"}], []])
        if self.maybe(0.2):
            p["index"] = self.index(2)
        return p

    def p_delete_choice_list(self, f: Facts) -> Any:
        return {"id": self.pick(f.lists), "cascade": self.maybe(0.5), "force": self.maybe(0.2)}

    def p_set_condition(self, f: Facts) -> Any:
        target = self.r.choice(
            [self.pick(f.qids), self.pick(f.qids), self.pick(f.nids), self.pick(f.quotas), self.pick(f.vids), self.pick(f.pages)]
        )
        p: dict[str, Any] = {"target": target, "condition": self.condition(f)}
        if self.maybe(0.3):
            p["field"] = self.r.choice(["showIf", "constraint", "if", "when", "expr", "bogus"])
        return p

    def p_insert_flow_node(self, f: Facts) -> Any:
        p: dict[str, Any] = {"node": self.node(f)}
        if self.maybe(0.35):
            parents = [n["id"] for n in f.nodes if n.get("type") in ("branch", "randomiser")]
            p["parent"] = self.pick(parents or f.nids)
            if self.maybe(0.5):
                p["arm"] = self.r.choice(["then", "else", "children"])
        elif self.maybe(0.05):
            p["arm"] = "then"
        if self.maybe(0.3):
            p["index"] = self.index(2)
        return p

    def p_delete_flow_node(self, f: Facts) -> Any:
        return {"id": self.pick(f.nids)}

    def p_move_flow_node(self, f: Facts) -> Any:
        p: dict[str, Any] = {"id": self.pick(f.nids)}
        if self.maybe(0.4):
            parents = [n["id"] for n in f.nodes if n.get("type") in ("branch", "randomiser")]
            p["parent"] = self.pick(parents or f.nids)
            if self.maybe(0.5):
                p["arm"] = self.r.choice(["then", "else", "children"])
        if self.maybe(0.5):
            p["index"] = self.index(3)
        return p

    def p_add_variable(self, f: Facts) -> Any:
        v = self.r.choice(
            [
                {"kind": "embedded", "param": "pid"},
                {"kind": "assigned", "levels": [1, 2]},
                {"kind": "computed", "expr": self.expr(f, 1)},
                {"kind": "bogus"},
                {"kind": "embedded", "param": "p", "id": self.pick(f.all_ids)},
            ]
        )
        if self.maybe(0.3):
            v = {"id": self.fresh("var"), **v}
        p: dict[str, Any] = {"variable": v}
        if self.maybe(0.2):
            p["index"] = self.index(2)
        return p

    def p_delete_variable(self, f: Facts) -> Any:
        return {"id": self.pick(f.vids), "cascade": self.maybe(0.5), "force": self.maybe(0.2)}

    def p_set_title(self, f: Facts) -> Any:
        return {"title": self.r.choice(["Plain", {lang: "T" for lang in f.langs}, {"en": "T", "xx-1": "U"}, {"type": "rich", "blocks": []}])}

    def p_set_languages(self, f: Facts) -> Any:
        langs = list(f.langs)
        roll = self.r.random()
        if roll < 0.3:
            new = langs + ["fr"]
        elif roll < 0.6:
            new = langs[:1]
        elif roll < 0.8:
            new = list(reversed(langs))
        else:
            new = self.r.choice([["de"], ["en", "en"], ["x!"]])
        p: dict[str, Any] = {"languages": new}
        if self.maybe(0.4):
            p["default_language"] = self.r.choice(new + [None])
        if self.maybe(0.4):
            p["cascade"] = True
        if self.maybe(0.2):
            p["force"] = True
        return p

    def p_set_consent(self, f: Facts) -> Any:
        return {
            "consent": self.r.choice(
                [None, {"text": "Agree?"}, {"text": {"en": "Agree?"}, "countDeclines": True}, {"text": self.label(f), "agreeLabel": "Yes", "declineLabel": {"type": "rich", "blocks": [{"type": "p", "content": [{"text": "No"}]}]}}, {"agreeLabel": "x"}, {"text": "T", "declineOutcome": "1bad"}]
            )
        }

    def p_set_ending(self, f: Facts) -> Any:
        ending = self.r.choice(
            [
                None,
                {},
                {"title": "Thanks", "body": "Bye ${%s}" % self.pick(f.qids)},
                {"body": {"en": "Done"}, "status": "none", "summary": "answers"},
                {"redirect": {"template": "prolific", "params": {"cc": "X1"}, "delay": 0, "mode": "link", "label": "Go"}},
                {"redirect": {"template": "t", "delay": 99}},
                {"status": "bad"},
                {"title": {"type": "rich", "blocks": [{"type": "p", "content": [{"text": "T"}]}]}},
                {"zz": 1},
            ]
        )
        return {"outcome": self.r.choice(["complete", "screened_out", "hook-failed", "quota_full", "bad-key", ""]), "ending": ending}

    def p_set_redirect_template(self, f: Facts) -> Any:
        template = self.r.choice(
            [
                None,
                {"url": "https://app.prolific.com/submissions/complete?cc={cc}", "params": {"cc": {"pattern": "[A-Z0-9]{4,8}"}}},
                {"url": "https://lab.example.org/done", "params": {}},
                {"url": 5, "params": {}},
                {"url": "https://x.org/{c}", "params": {"c": {"pattern": None}}},
                {"params": {}},
            ]
        )
        return {"name": self.r.choice(["prolific", "lab", "", "x" * 300]), "template": template}

    def p_set_theme(self, f: Facts) -> Any:
        from osp_spec.theme import PRESETS

        preset = PRESETS[self.r.choice(list(PRESETS))].model_dump(mode="json", by_alias=True)
        roll = self.r.random()
        if roll < 0.2:
            theme = None
        elif roll < 0.5:
            theme = preset
        elif roll < 0.65:
            theme = {**preset, "radius": self.r.choice([0, 12, 33]), "lineSpacing": self.r.choice([1.6, 2.5, 3])}
        elif roll < 0.8:
            theme = {"colours": preset["colours"], "headerText": self.r.choice(["Lab", {"en": "Lab"}, 5])}
        else:
            theme = self.r.choice([{}, {"colours": {"light": {}, "dark": 1}}, {**preset, "font": "comic"}, {**preset, "extra": 1}])
        return {"theme": theme}

    def p_set_hooks(self, f: Facts) -> Any:
        hooks = self.r.choice(
            [
                None,
                {"format": "osp-hooks/1", "source": "osp.on('onStart', function () {});", "handlers": {"onStart": {"reads": [self.pick(f.qids)], "writes": []}}},
                {"format": "osp-hooks/1", "source": "", "handlers": {}, "urlParams": ["PID"], "exportsConfirmedFor": None,
                 "redirects": {"done": {"url": "https://x.org/{c}", "params": {"c": {}}}},
                 "parent": {"origin": "https://x.org", "messages": {"p": {"type": "null"}, "q": {"type": "array", "items": {"type": "string", "maxLength": 3}, "maxItems": 2}}}},
                {"format": "osp-hooks/2", "source": "", "handlers": {"onNope": {}}},
                {"format": "osp-hooks/1", "source": "", "handlers": {}, "parent": {"origin": "o", "messages": {"m": {"type": "object", "properties": {"a": {"type": "object", "properties": {"b": {"type": "object", "properties": {"c": {"type": "object", "properties": {"d": {"type": "object", "properties": {}}}}}}}}}}}}},
                {"format": "osp-hooks/1", "source": "", "handlers": {"onStart": {"reads": [], "writes": [], "timeoutMs": 0}}},
            ]
        )
        return {"hooks": hooks}

    def p_insert_bank_item(self, f: Facts) -> Any:
        from test_bank_ops import BLOCK_FRAGMENT, SRC
        from test_guard import BANK_BLOCK, BANK_QUESTION, BANK_SRC

        frag = self.r.choice(
            [
                BANK_QUESTION,
                BANK_BLOCK,
                BLOCK_FRAGMENT,
                {"page": BANK_BLOCK["block"]["pages"][0], "choiceLists": BANK_BLOCK["choiceLists"], "variables": BANK_BLOCK["variables"]},
                {"question": {"id": "x", "type": "text", "label": "${outside}"}},
                {},
                {"question": {"id": "y", "type": "bogus"}},
            ]
        )
        src = self.r.choice([BANK_SRC, SRC, {**BANK_SRC, "library": "lab"}, {"bank": "x", "version": 0, "library": "nope"}, {**SRC, "checksum": "sha256:" + "0" * 64}])
        p: dict[str, Any] = {"fragment": frag, "source": src}
        kind = next((k for k in ("question", "page", "block") if k in frag), "question")
        if kind == "question" or self.maybe(0.1):
            p["page"] = self.pick(f.pages)
        if kind == "page" or self.maybe(0.1):
            p["block"] = self.pick(f.blocks)
        if kind == "block" and self.maybe(0.6):
            p["flow"] = {"after": self.r.choice([None, self.pick(f.nids)])}
        if self.maybe(0.3):
            p["index"] = self.index(2)
        return p

    def p_clear_source(self, f: Facts) -> Any:
        with_source = [o["id"] for o in f.questions if o.get("source")]
        for b in f.doc.get("blocks") or []:
            if b.get("source"):
                with_source.append(b["id"])
            for pg in b["pages"]:
                if pg.get("source"):
                    with_source.append(pg["id"])
        return {"target": self.pick(with_source or f.all_ids)}

    def p_replace_survey(self, f: Facts) -> Any:
        if self.maybe(0.15):
            return {"survey": self.r.choice([{}, {"specVersion": "osp-survey/0.1"}, {"specVersion": "x"}])}
        doc = copy.deepcopy(f.doc)
        doc.setdefault("metadata", {})["title"] = "Replaced " + self.fresh("t")
        return {"survey": doc}

    def p_apply_patch(self, f: Facts) -> Any:
        return {
            "patch": self.r.choice(
                [
                    [{"op": "replace", "path": "/metadata/title", "value": "P"}],
                    [{"op": "add", "path": "/metadata/license", "value": "MIT"}],
                    [{"op": "remove", "path": "/nope"}],
                    [{"op": "test", "path": "/id", "value": "x"}],
                    [{"op": "move", "from": "/blocks/0", "path": "/blocks/-"}],
                    [{"op": "copy", "from": "/metadata/title", "path": "/metadata/description"}],
                    [{"op": "bogus", "path": ""}],
                    [{"op": "add", "path": "/blocks/01", "value": 1}],
                    [{"op": "replace", "path": "", "value": f.doc}],
                    [{"op": "remove", "path": "/flow"}],
                    [],
                ]
            )
        }


# --- runs -------------------------------------------------------------------------------------------


def load_fixtures() -> dict[str, Any]:
    out: dict[str, Any] = {}
    from test_guard import BASE

    out["base"] = BASE
    for folder in sorted(FIXTURES.iterdir()):
        survey = folder / "survey.json"
        if survey.is_file():
            out[folder.name] = json.loads(survey.read_text("utf-8"))
    return out


def single_vectors(fixtures: dict[str, Any], ops: list[str]) -> tuple[list[Any], dict[str, Any]]:
    from osp_ops import invoke, run
    from test_guard import BASE, EXAMPLES

    cases: list[Any] = []
    docs: dict[str, Any] = {}

    def add(name: str, doc: Any, op_id: Any, params: Any) -> None:
        key = h(doc)
        docs[key] = doc
        res = run(op_id, doc, params)
        cases.append({"doc": key, "fixture": name, "op": op_id, "params": params, "result": op_result(res)})
        # The inverse (undo) and the inverse of the inverse (redo), run on the TS's own results.
        for _ in range(2):
            if not res.ok or res.inverse is None:
                break
            res = invoke(res.inverse, res.survey)
            cases.append({"chain": len(cases) - 1, "result": op_result(res)})

    for op_id, examples in sorted(EXAMPLES.items()):
        for p in examples:
            add("base", BASE, op_id, p)
        # Near misses: the examples with fields dropped, added or swapped for other values
        # (the guard's Hypothesis fuzz, made deterministic).
        r = random.Random(f"near:{op_id}")
        seen = [v for ps in EXAMPLES.values() for p in ps for v in p.values()]
        for _ in range(30):
            p = dict(r.choice(examples))
            roll = r.random()
            if roll < 0.3 and p:
                del p[r.choice(list(p))]
            elif roll < 0.8 and p:
                p[r.choice(list(p))] = r.choice(seen + HOSTILE + BAD_IDS)
            else:
                p = mutate(r, p)
            add("base", BASE, op_id, p)
    for name, doc in fixtures.items():
        r = random.Random(f"single:{name}")
        g = Gen(r)
        for op_id in ops:
            for _ in range(3):
                add(name, doc, op_id, g.params(op_id, Facts(doc)))
    # Shapes the fixtures lack: no `settings`, an externalTask node, named scoring variables.
    from test_guard import BANK_SRC, MINIMAL

    no_settings = {k: v for k, v in BASE.items() if k != "settings"}
    external = copy.deepcopy(BASE)
    external["flow"].append({"type": "externalTask", "id": "n_ext", "template": "t"})
    named = copy.deepcopy(EXAMPLES["insert_bank_item"][1]["fragment"])
    named["variables"][0]["name"] = "age"
    extras: list[tuple[str, Any, str, Any]] = [
        ("minimal", MINIMAL, "set_property", {"target": "/settings", "property": "backNavigation", "value": False}),
        ("minimal", MINIMAL, "set_property", {"target": "/settings", "property": "saveMode", "unset": True}),
        ("minimal", MINIMAL, "set_ending", {"outcome": "complete", "ending": {"title": "T"}}),
        ("minimal", MINIMAL, "set_ending", {"outcome": "complete", "ending": None}),
        ("minimal", MINIMAL, "set_redirect_template", {"name": "a", "template": {"url": "https://x.org/", "params": {}}}),
        ("minimal", MINIMAL, "set_redirect_template", {"name": "a", "template": None}),
        ("minimal", MINIMAL, "set_theme", {"theme": None}),
        ("no_settings", no_settings, "set_theme", {"theme": {"colours": EXAMPLES["set_theme"][0]["theme"]["colours"]}}),
        ("no_settings", no_settings, "set_property", {"target": "/settings", "property": "resumeExpiryDays", "value": 9}),
        ("external", external, "set_property", {"target": "n_ext", "property": "template", "value": "u"}),
        ("external", external, "set_condition", {"target": "n_ext", "condition": None}),
        ("external", external, "insert_flow_node", {"node": {"type": "end"}, "parent": "n_ext"}),
        ("external", external, "move_flow_node", {"id": "n_ext", "index": 0}),
        ("base", BASE, "set_condition", {"target": "age", "condition": "x" * 20001}),
        ("base", BASE, "add_question", {"page": "p_demo", "question": {"type": "text", "label": "L", "custom": 5}, "defaults": {"custom.k": 1}}),
        ("base", BASE, "insert_bank_item", {"fragment": named, "source": BANK_SRC}),
        ("base", BASE, "insert_bank_item", {"fragment": named, "source": BANK_SRC, "flow": {"after": "n_rand"}}),
        ("base", BASE, "add_matrix_row", {"question": "grid", "id": "a" * 70}),
        ("base", BASE, "bulk_paste_choices", {"owner": "spare", "text": "\n".join(f"L{i}" for i in range(3000)), "mode": "append"}),
    ]
    for name, doc, op_id, params in extras:
        add(name, doc, op_id, params)
    # Hostile surveys and invocations.
    r = random.Random("hostile")
    hostile_docs = [None, 5, "x", [], {}, {"specVersion": "osp-survey/0.1"}, {"specVersion": "osp-survey/9"}, [BASE]]
    for op_id in ops:
        for doc in r.sample(hostile_docs, 3):
            add("hostile", doc, op_id, EXAMPLES[op_id][0])
    for bad in [None, 5, "nope", ["x"], {"a": 1}, "add_questions"]:
        add("base", BASE, bad, {})
    return cases, docs


def run_sequence(seed: int, fixtures: dict[str, Any], ops: list[str]) -> dict[str, Any]:
    from osp_ops import Draft, apply_transaction, run

    r = random.Random(f"seq:{seed}")
    g = Gen(r, hostility=[0.2, 0.5, 1.0, 1.5][seed % 4])
    names = sorted(fixtures)
    name = "base" if seed % 3 == 0 else r.choice(names)
    doc = fixtures[name]
    rev = r.randint(0, 3)
    start = {"fixture": name, "doc": h(doc), "revision": rev}
    weights = {o: 1.0 for o in ops}
    for o in ("replace_survey", "apply_patch", "set_theme", "set_hooks"):
        weights[o] = 0.25
    for o in ("add_question", "set_property", "set_condition", "add_choice", "insert_flow_node", "delete_question"):
        weights[o] = 2.0
    pool, w = list(weights), list(weights.values())
    undo: list[list[Any]] = []
    redo: list[list[Any]] = []
    steps: list[Any] = []
    for _ in range(r.randint(*STEPS)):
        roll = r.random()
        if roll < 0.1 and undo:
            inv = undo.pop()
            res = apply_transaction(Draft(survey=doc, revision=rev), inv, rev)
            steps.append({"kind": "undo", "result": tx_result(res)})
            if res.ok:
                doc, rev = res.draft.survey, res.draft.revision
                redo.append(res.inverse)
            continue
        if roll < 0.15 and redo:
            inv = redo.pop()
            res = apply_transaction(Draft(survey=doc, revision=rev), inv, rev)
            steps.append({"kind": "redo", "result": tx_result(res)})
            if res.ok:
                doc, rev = res.draft.survey, res.draft.revision
                undo.append(res.inverse)
            continue
        if roll < 0.45:
            op_id = r.choices(pool, w)[0]
            params = g.params(op_id, Facts(doc))
            res = run(op_id, doc, params)
            steps.append({"kind": "run", "op": op_id, "params": params, "result": op_result(res)})
            if res.ok:
                doc = res.survey
                rev += 1 if res.patch else 0
                undo.append([res.inverse.model_dump(mode="json")])
                redo.clear()
            continue
        batch = []
        cur = doc
        for _ in range(r.randint(1, 4 if g.hostility > 0.5 else 2)):
            op_id = r.choices(pool, w)[0]
            batch.append({"op": op_id, "params": g.params(op_id, Facts(cur))})
        if r.random() < 0.04:
            batch.append(r.choice([5, None, {"op": "nope"}, {"params": {}}]))
        base = rev if r.random() > 0.05 else r.choice([rev - 1, rev + 1, str(rev), True, None])
        res = apply_transaction(Draft(survey=doc, revision=rev), batch, base)
        steps.append({"kind": "tx", "ops": batch, "base": base, "result": tx_result(res)})
        if res.ok:
            doc, rev = res.draft.survey, res.draft.revision
            if res.patch:
                undo.append([i.model_dump(mode="json") for i in res.inverse])
                redo.clear()
    return {"seed": seed, "start": start, "steps": steps, "final": doc}


def _sequence_worker(args: tuple[list[int], list[str]]) -> tuple[list[Any], dict[str, Any]]:
    seeds, ops = args
    install_recorders()
    fixtures = load_fixtures()
    out = [run_sequence(s, fixtures, ops) for s in seeds]
    return out, ORACLE


# --- calls harvested from the osp-ops test suite -------------------------------------------------------

MAX_SAFE = 2**53 - 1


def js_safe(v: Any) -> bool:
    """Whether JSON.parse/JSON.stringify keep `v` exactly: no integral or exponent-formatted
    floats, no ints past 2^53, no lone surrogates, no integer-like object keys (JS moves
    those to the front)."""
    if v is None or isinstance(v, bool):
        return True
    if isinstance(v, int):
        return abs(v) <= MAX_SAFE
    if isinstance(v, float):
        return v == v and not v.is_integer() and 1e-4 <= abs(v) < 1e16
    if isinstance(v, str):
        try:
            v.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return True
    if isinstance(v, list):
        return all(js_safe(x) for x in v)
    if isinstance(v, dict):
        return all(
            isinstance(k, str) and js_safe(k) and not (k.isdigit() and k.isascii()) and js_safe(x)
            for k, x in v.items()
        )
    return False


# One pytest run per group, in parallel (test_guard's fuzzers are most of the time).
HARVEST_GROUPS: list[list[str]] = [
    ["test_guard.py", "-k", "near_miss_params"],
    ["test_guard.py", "-k", "hostile_params"],
    ["test_guard.py", "-k", "not near_miss_params and not hostile_params"],
    ["test_ops.py"],
    ["test_bank_ops.py", "test_bank_provenance.py"],
    ["test_question_type.py", "test_matrix_rows.py"],
    ["test_richtext_ops.py", "test_hooks_ops.py", "test_custom_property.py"],
]


def _harvest_worker(group: list[str]) -> tuple[list[Any], dict[str, Any], dict[str, Any]]:
    """Run python/osp-ops/tests with every `run`, `invoke` and `apply_transaction` call
    recorded (the hand-written cases and the Hypothesis fuzzers, seeded)."""
    import contextlib
    import io

    install_recorders()
    import osp_ops
    import pytest

    calls: list[Any] = []
    docs: dict[str, Any] = {}
    real_run, real_invoke, real_tx = osp_ops.run, osp_ops.invoke, osp_ops.apply_transaction

    def keep(doc: Any, *rest: Any) -> str | None:
        if not all(js_safe(x) for x in (doc, *rest)):
            return None
        key = h(doc)
        docs[key] = snap(doc)  # the tests mutate their surveys after a call
        return key

    def snap(v: Any) -> Any:
        return json.loads(json.dumps(v))

    def run(op_id: Any, survey: Any, params: Any = None) -> Any:
        res = real_run(op_id, survey, params)
        if len(calls) < 20000 and js_safe(res.survey) and js_safe(res.patch):
            key = keep(survey, op_id, params)
            if key is not None:
                calls.append(snap({"kind": "run", "doc": key, "op": op_id, "params": params, "result": op_result(res)}))
        return res

    def invoke(inv: Any, survey: Any) -> Any:
        res = real_invoke(inv, survey)
        raw = inv.model_dump(mode="json") if isinstance(inv, osp_ops.Invocation) else inv
        if len(calls) < 20000 and js_safe(res.survey) and js_safe(res.patch):
            key = keep(survey, raw)
            if key is not None:
                calls.append(snap({"kind": "invoke", "doc": key, "inv": raw, "result": op_result(res)}))
        return res

    def apply_transaction(draft: Any, ops: Any, base_revision: Any) -> Any:
        res = real_tx(draft, ops, base_revision)
        raw = [o.model_dump(mode="json") if isinstance(o, osp_ops.Invocation) else o for o in ops] if isinstance(ops, (list, tuple)) else ops
        if len(calls) < 20000 and js_safe(res.draft.survey) and js_safe(res.patch):
            key = keep(draft.survey, raw, base_revision)
            if key is not None:
                calls.append(snap({"kind": "tx", "doc": key, "revision": draft.revision, "ops": raw, "base": base_revision, "result": tx_result(res)}))
        return res

    osp_ops.run, osp_ops.invoke, osp_ops.apply_transaction = run, invoke, apply_transaction
    with contextlib.redirect_stdout(io.StringIO()):
        args = [str(TESTS / a) if a.endswith(".py") else a for a in group]
        code = pytest.main([*args, "-q", "-p", "no:cacheprovider", "--hypothesis-seed=0", "-x"])
    if code not in (0, 5):  # 5: the -k selected nothing
        raise SystemExit(f"python/osp-ops tests failed while harvesting (exit {code})")
    return calls, docs, ORACLE


# --- model and helper vectors -----------------------------------------------------------------------


def mutate(r: random.Random, v: Any, depth: int = 0) -> Any:
    roll = r.random()
    if roll < 0.15 or depth > 4:
        return r.choice(HOSTILE + ["osp-hooks/1", "#ffffff", "auto", "rich", "p", "ref", "and", "sha256:" + "a" * 64])
    if isinstance(v, dict):
        out = dict(v)
        keys = list(out)
        roll = r.random()
        if roll < 0.25 and keys:
            del out[r.choice(keys)]
        elif roll < 0.4:
            out[r.choice(["extra", "type", "kind", "else_", "id", "value", "zz"])] = r.choice(HOSTILE)
        elif keys:
            k = r.choice(keys)
            out[k] = mutate(r, out[k], depth + 1)
        return out
    if isinstance(v, list):
        out = list(v)
        roll = r.random()
        if roll < 0.3 and out:
            out.pop(r.randrange(len(out)))
        elif roll < 0.5:
            out.append(r.choice(HOSTILE))
        elif out:
            i = r.randrange(len(out))
            out[i] = mutate(r, out[i], depth + 1)
        return out
    return r.choice(HOSTILE + [v])


def model_vectors() -> dict[str, Any]:
    from osp_expr.ast import EXPR_ADAPTER
    from osp_ops import REGISTRY
    from osp_spec.hooks import Hooks, hooks_json
    from osp_spec.model import Ending, RedirectTemplate, Source
    from osp_spec.theme import PRESETS, Theme
    from pydantic import ValidationError
    from test_guard import EXAMPLES

    def errors(e: ValidationError) -> list[Any]:
        return [{"type": x["type"], "loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors(include_url=False, include_input=False)]

    rich = {"type": "rich", "blocks": [{"type": "p", "content": [{"text": "a", "marks": ["b"], "href": "https://x.org", "lang": "en"}, {"pipe": "q"}, {"br": True}]}, {"type": "h", "level": 2, "content": []}, {"type": "ul", "items": [[{"text": "i"}]]}]}
    seeds: dict[str, tuple[Any, Any, list[Any]]] = {
        "Ending": (Ending, lambda m: m.model_dump(mode="json", exclude_unset=True), [
            {"title": "T", "body": {"en": "B", "de": rich}, "status": "none", "summary": "answers", "redirect": {"template": "t", "params": {"a": "${q}"}, "delay": 3, "mode": "link", "label": rich}},
            {}, {"title": None}, {"redirect": {"template": "t"}},
        ]),
        "RedirectTemplate": (RedirectTemplate, lambda m: m.model_dump(mode="json", exclude_none=True), [
            {"url": "https://x.org/{a}", "params": {"a": {"pattern": "[0-9]+"}, "b": {}}},
        ]),
        "Source": (Source, lambda m: m.model_dump(mode="json", exclude_none=True), [
            {"bank": "phq9", "version": 2, "library": "bundled", "item": "q1", "checksum": "sha256:" + "a" * 64},
        ]),
        "Hooks": (Hooks, hooks_json, [
            {"format": "osp-hooks/1", "source": "x", "handlers": {"onStart": {"reads": ["a"], "writes": ["b"], "timeoutMs": 100}}, "urlParams": ["p"], "redirects": {"r": {"url": "https://x.org/{c}", "params": {"c": {"pattern": None}}}}, "parent": {"origin": "https://x.org", "messages": {"m": {"type": "object", "properties": {"a": {"type": "number", "minimum": 1, "maximum": 2.5}, "b": {"type": "integer"}, "c": {"type": "string", "maxLength": 3, "pattern": "x", "enum": ["x"]}, "d": {"type": "boolean"}, "e": {"type": "array", "items": {"type": "null"}, "maxItems": 3}}, "required": ["a"]}}}, "exportsConfirmedFor": "sha"},
        ]),
        "Theme": (Theme, lambda m: m.model_dump(mode="json", by_alias=True), [
            PRESETS[k].model_dump(mode="json", by_alias=True) for k in PRESETS
        ] + [{"colours": PRESETS["clean"].model_dump(mode="json")["colours"], "headerText": {"en": "x"}, "logoAssetId": "a_b"}]),
        "Expr": (None, None, [
            {"kind": "and", "args": [{"kind": "compare", "op": ">=", "left": {"kind": "ref", "id": "age"}, "right": {"kind": "decimal", "value": "1.50"}}, {"kind": "contains", "ref": {"kind": "ref", "id": "m"}, "value": {"kind": "text", "value": "a"}}, {"kind": "not", "arg": {"kind": "bool", "value": False}}]},
            {"kind": "if", "cond": {"kind": "answered", "ref": {"kind": "ref", "id": "q"}}, "then": {"kind": "arith", "op": "/", "left": {"kind": "int", "value": 1}, "right": {"kind": "decimal", "value": 2}}, "else_": {"kind": "null"}},
            {"kind": "decimal", "value": "-0.000"}, {"kind": "decimal", "value": "1_000.5"}, {"kind": "decimal", "value": "1e-9"}, {"kind": "decimal", "value": 2.5},
            {"kind": "or", "args": [{"kind": "null"}, {"kind": "ref", "id": "x"}]},
        ]),
    }
    for op_id, spec in sorted(REGISTRY.items()):
        seeds["params:" + op_id] = (spec.params, lambda m: m.model_dump(mode="json"), list(EXAMPLES[op_id]))
    out: dict[str, Any] = {}
    for name, (cls, dump, examples) in seeds.items():
        r = random.Random("models:" + name)
        rows = []
        inputs = list(examples)
        for _ in range(90 if not name.startswith("params:") else 45):
            inputs.append(mutate(r, copy.deepcopy(r.choice(examples))))
        for inp in inputs:
            try:
                if cls is None:
                    m = EXPR_ADAPTER.validate_python(inp)
                    rows.append({"input": inp, "dump": EXPR_ADAPTER.dump_python(m, mode="json")})
                else:
                    rows.append({"input": inp, "dump": dump(cls.model_validate(inp))})
            except ValidationError as e:
                rows.append({"input": inp, "errors": errors(e)})
        out[name] = rows
    return out


def py_vectors() -> dict[str, Any]:
    r = random.Random("py")
    alphabet = ["a", "Z", " ", "'", '"', "\\", "\t", "\n", "\r", "\x0b", "\x0c", "\x1c", "\x1f", "\x85", "\xa0", "é", " ", "　", "﻿", "​", "😀", "\x00", "\x7f", "日"]
    strings = ["", "'", '"', "'\"", "a'b", "x" * 5]
    for _ in range(400):
        strings.append("".join(r.choice(alphabet) for _ in range(r.randint(1, 8))))
    decimals = ["1", "-0", "0.000", "1.50", "1e3", "1E+3", "-12.5e-8", ".5", "5.", "1_000", "00.10", " 7 ", "abc", "1e", "inf", "-Infinity", "nan", "1.2.3", "", "+3", "1e-7", "123456789012345678901234567890", "0e5", "0.0001", "0.00000001"]
    floats = [0.5, 2.5, 1.6, -0.25, 1e-5, 1.5e-7, 1e22, 123456.789, 0.1, 1 / 3, 1.5e16, 3.14159]

    def dec(s: str) -> Any:
        try:
            d = Decimal(s.strip())
        except InvalidOperation:
            return None
        return "special" if not d.is_finite() else str(d)

    return {
        "repr": [[s, repr(s)] for s in strings],
        "strip": [[s, s.strip()] for s in strings],
        "splitlines": [[s, s.splitlines()] for s in strings],
        "decimal": [[s, dec(s)] for s in decimals],
        "float": [[f, repr(f)] for f in floats],
    }


def field_vectors() -> dict[str, Any]:
    from osp_ops import REGISTRY
    from osp_ops.property_ops import FIXED_CLASSES, NODE_CLASSES, QUESTION_CLASSES, SINGLETONS, VARIABLE_CLASSES, model_fields

    def table(t: dict[str, Any]) -> dict[str, Any]:
        return {k: {"name": c.__name__, "fields": model_fields(c)} for k, c in t.items()}

    return {
        "ops": [{"id": s.id, "label": s.label, "area": s.area, "wholeDocument": s.whole_document} for s in sorted(REGISTRY.values(), key=lambda s: s.id)],
        "question": table(QUESTION_CLASSES),
        "node": table(NODE_CLASSES),
        "variable": table(VARIABLE_CLASSES),
        "fixed": table(FIXED_CLASSES),
        "singletons": {k: {"name": c.__name__, "fields": model_fields(c)} for k, (_, c) in SINGLETONS.items()},
    }


# --- main ---------------------------------------------------------------------------------------------


def stamp() -> str:
    hasher = hashlib.sha256()
    paths = [Path(__file__)]
    for pkg in ("osp-ops", "osp-spec", "osp-expr"):
        paths += sorted((ROOT / "python" / pkg / "src").rglob("*.py"))
    paths += sorted(TESTS.glob("*.py")) + sorted(TESTS.glob("*.json"))
    paths += sorted(FIXTURES.glob("*/survey.json"))
    for p in paths:
        hasher.update(str(p.relative_to(ROOT)).encode())
        hasher.update(p.read_bytes())
    return hasher.hexdigest()


def write(name: str, data: Any) -> None:
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), "utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    st = stamp()
    stamp_file = OUT / "stamp.txt"
    if "--force" not in sys.argv and stamp_file.exists() and stamp_file.read_text() == st:
        print("ops vectors: up to date")
        return
    stamp_file.unlink(missing_ok=True)
    install_recorders()
    from osp_ops import REGISTRY

    ops = sorted(REGISTRY)
    fixtures = load_fixtures()
    chunks = [list(range(i, N_SEQUENCES, 6)) for i in range(6)]
    sequences: list[Any] = []
    calls: list[Any] = []
    call_docs: dict[str, Any] = {}
    with ProcessPoolExecutor(max_workers=len(HARVEST_GROUPS) + len(chunks)) as pool:
        harvests = [pool.submit(_harvest_worker, g) for g in HARVEST_GROUPS]
        seq_jobs = [pool.submit(_sequence_worker, (c, ops)) for c in chunks]
        write("fields.json", field_vectors())
        write("models.json", model_vectors())
        write("py.json", py_vectors())
        cases, docs = single_vectors(fixtures, ops)
        write("single.json", {"docs": docs, "cases": cases})
        for job in seq_jobs:
            seqs, oracle = job.result()
            sequences += seqs
            for k in ORACLE:
                ORACLE[k].update(oracle[k])
        for job in harvests:
            got, got_docs, oracle = job.result()
            calls += got
            call_docs.update(got_docs)
            for k in ORACLE:
                ORACLE[k].update(oracle[k])
    write("tests.json", {"docs": call_docs, "calls": calls})
    sequences.sort(key=lambda s: s["seed"])
    starts = {s["start"]["doc"]: fixtures[s["start"]["fixture"]] for s in sequences}
    finals = {}
    for s in sequences:
        finals[h(s["final"])] = s["final"]
        s["final"] = h(s["final"])
    write("sequences.json", {"docs": {**starts, **finals}, "sequences": sequences})
    write("oracle.json", ORACLE)
    n_ops = sum(len(st["ops"]) if st["kind"] == "tx" else 1 for s in sequences for st in s["steps"] if st["kind"] in ("tx", "run"))
    print(
        f"ops vectors: {len(cases)} single cases, {len(calls)} calls from the osp-ops tests, "
        f"{len(sequences)} sequences "
        f"({sum(len(s['steps']) for s in sequences)} steps, {n_ops} ops), "
        f"oracle {len(ORACLE['parse'])} documents -> {OUT.relative_to(ROOT)}"
    )
    stamp_file.write_text(st)


if __name__ == "__main__":
    main()
