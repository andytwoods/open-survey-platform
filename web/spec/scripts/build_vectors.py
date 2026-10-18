"""Validator parity vectors for @osp/spec (task CE4) into web/spec/.build/ (gitignored):

    uv run python web/spec/scripts/build_vectors.py

`.build/vectors.json` is a list of `{"name", "doc", "diagnostics"}`: every input document and
the diagnostics `osp_spec.validate` gives it (`Diagnostic.model_dump()`, in order). The
documents are

1. every fixture survey (fixtures/*/survey.json);
2. every validator test case (python/osp-spec/tests/cases) and every input the osp-spec test
   suite passes to the validator (test/vectors/spec-test-inputs.json, harvest_spec_tests.py);
3. seeded mutations of the fixtures and valid cases: deleted keys, renamed and duplicated
   ids, broken references, wrong types, extra keys, wrong tags, too-long text, rich text
   with bad links and wrong levels, translations, pipes, random expressions, names that
   differ only in case, numbers and sliders, flow nodes, variables, quotas, endings,
   redirect templates, external tasks, consent, hooks and themes;
4. random JSON (like test_fuzz.py's Hypothesis strategy).

Every document is first put into the shape a JavaScript engine gives it after JSON.parse:
object keys in JavaScript order (array-index keys first, ascending) and no number JavaScript
cannot tell apart (integral floats, unsafe integers, NaN/inf); see web/spec/README.md.
"""

from __future__ import annotations

import copy
import json
import os
import random
import sys
from pathlib import Path
from typing import Any

from osp_spec import CODES, validate

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "web" / "spec" / ".build"
HARVEST = ROOT / "web" / "spec" / "test" / "vectors" / "spec-test-inputs.json"
# OSP_SPEC_SEED / OSP_SPEC_MUTANTS override these for a longer local soak.
SEED = int(os.environ.get("OSP_SPEC_SEED", "20261018"))
MUTANTS = int(os.environ.get("OSP_SPEC_MUTANTS", "5000"))
RANDOM_JSON = MUTANTS // 8

# --- JavaScript shape --------------------------------------------------------------------


def _is_index(key: str) -> bool:
    return key.isdigit() and key.isascii() and str(int(key)) == key and int(key) < 2**32 - 1


def js_order(value: Any) -> Any:
    """`value` as JSON.parse would order it: array-index keys first (ascending)."""
    if isinstance(value, dict):
        keys = list(value)
        idx = sorted((k for k in keys if _is_index(k)), key=int)
        rest = [k for k in keys if not _is_index(k)]
        return {k: js_order(value[k]) for k in idx + rest}
    if isinstance(value, list):
        return [js_order(v) for v in value]
    return value


def js_safe(value: Any) -> bool:
    """No number whose Python type JavaScript cannot recover from the JSON text."""
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, str):
        # json.loads never yields a surrogate pair as two code points; JavaScript would join it.
        return not any(
            "\ud800" <= a <= "\udbff" and "\udc00" <= b <= "\udfff"
            for a, b in zip(value, value[1:], strict=False)
        )
    if isinstance(value, int):
        # Exactly a double, and printed in full by JavaScript's String() (below 1e21).
        return abs(value) < 10**21 and int(float(value)) == value
    if isinstance(value, float):
        return value == value and abs(value) != float("inf") and not value.is_integer()
    if isinstance(value, list):
        return all(js_safe(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and js_safe(k) for k in value) and all(
            js_safe(v) for v in value.values()
        )
    return False


# --- Mutations ---------------------------------------------------------------------------

TEXT_KEYS = {
    "label",
    "help",
    "title",
    "text",
    "body",
    "message",
    "constraintMessage",
    "description",
    "minLabel",
    "maxLabel",
    "agreeLabel",
    "declineLabel",
}
EXPR_KEYS = {"showIf", "constraint", "if", "when", "expr"}
REF_KEYS = {"block", "quota", "choiceList", "template", "outcome"}
SCALARS: list[Any] = [
    None,
    True,
    False,
    0,
    1,
    -1,
    7,
    2.5,
    -0.5,
    "",
    "x",
    "Q1",
    "and",
    "seed",
    "a b",
    "${q1}",
    [],
    {},
    [1],
    {"kind": "null"},
    "x" * 70,
    "1.5",
    "١٢",
    "rich",
    "en",
    "p",
    "single",
    "osp-survey/0.2",
    10**20,
]
WEIRD_IDS = [
    "and",
    "not",
    "null",
    "seed",
    "SEED",
    "_x",
    "a__state",
    "1x",
    "a-b",
    "x" * 65,
    "Id",
    "instanceID",
    "q1",
    "Q1",
    "page_1",
    "ok_id",
    "true",
]
BUILTINS = [
    "$trial",
    "$position.index",
    "$pagesDone",
    "$language",
    "$device",
    "$response.id",
    "$session.id",
    "$outcome",
    "$nope",
    " q1 ",
    "",
    "1x",
    "a b",
]
URLS = [
    "https://lab.example.org/t/{pid}",
    "https://lab.example.org/{a}/{b}",
    "http://x.org/{a}",
    "https://{a}.example.org/x",
    "https://lab.example.org",
    "ftp://x/{a}",
    "not a url",
    "https://LAB.example.org/x/{a}",
    "https://lab.example.org:443/x/{a}",
    "https://lab.example.org:8443/x/{a}",
    "https://lab.example.org/{a}/{a}",
    "https://lab.example.org/x/{osp_token}",
    "https://lab.example.org/x\n",
    "https://[::1]/x/{a}",
    "https://lab.example.org/x y/{a}",
]
PATTERNS = [
    None,
    "",
    "[0-9]+",
    "[a-z]{1,3}",
    "\\d{3}",
    "(",
    "[a-",
    "a|b",
    "x*",
    "\\w+",
    "a{2,}",
    "(?P<n>a)(?P=n)",
    "[A-Z]",
    ".*",
    "a{,2}",
    "\\s",
    "{",
    "a{99999999999}",
]
WEIRD_STRINGS = [
    "it's",
    'say "hi"',
    "both ' and \"",
    "back\\slash",
    "tab\there",
    "new\nline",
    "trail\n",
    "\x00nul",
    "\x7f",
    "é",
    "日本語",
    "😀",
    "\ud800",
    "a\u200bb",
    "\u2028",
    "\ufeff",
    "\x1c",
    " ",
    "\u00a0x",
    "١٢٣",
    "x" * 45,
    "1",
    "10",
    "2",
    "__proto__",
    "constructor",
    "toString",
    "${q1}",
    "${ q1 }",
    "${}",
    "${$trial}",
    "~/x",
    "a/b",
]
HREFS = [
    "https://example.org/a",
    "http://example.org",
    "",
    "https://",
    "javascript:alert(1)",
    "https://ex ample.org",
    "mailto:a@b.c",
    "https://example.org/" + "x" * 1990,
]


class Mutator:
    def __init__(self, rng: random.Random, doc: Any) -> None:
        self.r = rng
        self.doc = doc
        self.ids: list[str] = []
        self.names: list[str] = []
        self._collect(doc)
        if not self.ids:
            self.ids = ["q1"]

    def _collect(self, v: Any) -> None:
        if isinstance(v, dict):
            if isinstance(v.get("id"), str):
                self.ids.append(v["id"])
            if isinstance(v.get("name"), str):
                self.names.append(v["name"])
            for x in v.values():
                self._collect(x)
        elif isinstance(v, list):
            for x in v:
                self._collect(x)

    # helpers
    def nodes(self) -> list[tuple[Any, Any]]:
        """(container, key) of every value below the root."""
        out: list[tuple[Any, Any]] = []
        stack = [self.doc]
        while stack:
            c = stack.pop()
            if isinstance(c, dict):
                for k, v in c.items():
                    out.append((c, k))
                    stack.append(v)
            elif isinstance(c, list):
                for i, v in enumerate(c):
                    out.append((c, i))
                    stack.append(v)
        return out

    def dicts(self, pred: Any = None) -> list[dict]:
        out: list[dict] = []
        stack = [self.doc]
        while stack:
            c = stack.pop()
            if isinstance(c, dict):
                if pred is None or pred(c):
                    out.append(c)
                stack.extend(c.values())
            elif isinstance(c, list):
                stack.extend(c)
        return out

    def where(self, keys: set[str]) -> list[tuple[dict, str]]:
        return [(c, k) for c, k in self.nodes() if isinstance(c, dict) and k in keys]

    def pick(self, xs: list[Any]) -> Any:
        return xs[self.r.randrange(len(xs))] if xs else None

    def ident(self) -> str:
        r = self.r.random()
        if r < 0.5:
            return self.pick(self.ids)
        if r < 0.75:
            return self.pick(WEIRD_IDS)
        return "v" + str(self.r.randrange(1000))

    def survey(self) -> dict | None:
        return self.doc if isinstance(self.doc, dict) else None

    def langs(self) -> list[str]:
        s = self.survey()
        md = s.get("metadata") if s else None
        langs = md.get("languages") if isinstance(md, dict) else None
        return [x for x in langs if isinstance(x, str)] if isinstance(langs, list) else ["en"]

    # generators
    def expr(self, depth: int = 0) -> Any:
        r = self.r
        leaf = depth >= 3 or r.random() < 0.35
        if leaf:
            k = r.randrange(9)
            if k < 3:
                return {"kind": "ref", "id": self.ident()}
            if k == 3:
                return {"kind": "int", "value": r.choice([0, 1, 2, 5, -3, 99])}
            if k == 4:
                return {"kind": "text", "value": r.choice(["a", "b", "1", "yes", ""])}
            if k == 5:
                return {
                    "kind": "decimal",
                    "value": r.choice(["1.5", "0", "0.0", 2.5, "1e3", "x", "NaN"]),
                }
            if k == 6:
                return {"kind": "bool", "value": r.choice([True, False, 1])}
            if k == 7:
                return {"kind": "null"}
            return r.choice(
                [{"kind": "zz"}, {"id": "q1"}, 5, {"kind": "ref"}, {"kind": "ref", "id": "and"}]
            )
        k = r.randrange(8)
        if k == 0:
            return {
                "kind": "compare",
                "op": r.choice(["==", "!=", "<", ">=", "~"]),
                "left": self.expr(depth + 1),
                "right": self.expr(depth + 1),
            }
        if k == 1:
            return {
                "kind": "arith",
                "op": r.choice(["+", "-", "*", "/"]),
                "left": self.expr(depth + 1),
                "right": self.expr(depth + 1),
            }
        if k in (2, 3):
            n = r.choice([1, 2, 2, 3])
            return {
                "kind": r.choice(["and", "or"]),
                "args": [self.expr(depth + 1) for _ in range(n)],
            }
        if k == 4:
            return {"kind": "not", "arg": self.expr(depth + 1)}
        if k == 5:
            return {"kind": "answered", "ref": {"kind": "ref", "id": self.ident()}}
        if k == 6:
            return {
                "kind": "contains",
                "ref": {"kind": "ref", "id": self.ident()},
                "value": self.expr(depth + 1),
            }
        return {
            "kind": "if",
            "cond": self.expr(depth + 1),
            "then": self.expr(depth + 1),
            "else": self.expr(depth + 1),
        }

    def run_(self) -> Any:
        r = self.r
        k = r.random()
        if k < 0.7:
            return {
                "text": r.choice(["a", "hello", "", "x" * r.choice([10, 499, 501, 2001])]),
                **(
                    {"marks": r.choice([["b"], ["i", "b"], ["b", "b"], ["u"]])}
                    if r.random() < 0.3
                    else {}
                ),
                **({"href": r.choice(HREFS)} if r.random() < 0.3 else {}),
                **({"lang": r.choice(["en", "fr", "x"])} if r.random() < 0.1 else {}),
            }
        if k < 0.9:
            return {"pipe": r.choice([self.ident(), *BUILTINS])}
        return r.choice([{"br": True}, {"br": False}, {"text": "a", "pipe": "q1"}, "x", {}])

    def rich(self) -> Any:
        r = self.r
        blocks = []
        for _ in range(r.choice([0, 1, 1, 1, 2, 3])):
            k = r.randrange(5)
            runs = [self.run_() for _ in range(r.choice([0, 1, 2, 3]))]
            if k <= 1:
                blocks.append({"type": "p", "content": runs})
            elif k == 2:
                blocks.append({"type": "h", "level": r.choice([1, 2, 3, 4]), "content": runs})
            elif k == 3:
                items = [[self.run_()] for _ in range(r.choice([1, 2, 101]))]
                blocks.append({"type": r.choice(["ul", "ol"]), "items": items})
            else:
                blocks.append(r.choice([{"type": "q"}, {"type": "p"}, 5]))
        if r.random() < 0.03:
            blocks = [{"type": "p", "content": [{"text": "a"}]} for _ in range(201)]
        return {"type": "rich", "blocks": blocks}

    def text(self) -> Any:
        r = self.r
        k = r.random()
        if k < 0.35:
            pipes = "".join(
                "${" + r.choice([self.ident(), *BUILTINS]) + "}" for _ in range(r.randrange(3))
            )
            return r.choice(["Hi ", "", "x" * r.choice([1, 499, 501, 1999, 2001, 20001])]) + pipes
        if k < 0.7:
            return self.rich()
        langs = self.langs() + ["fr", "zz-1", "1x"]
        m = {
            lang: (self.rich() if r.random() < 0.3 else "t")
            for lang in r.sample(langs, r.randrange(1, 4))
        }
        return m

    def flow_node(self, depth: int = 0) -> Any:
        r = self.r
        k = r.randrange(9)
        nid = self.ident()
        if k == 0 or depth > 1:
            return {"type": "block", "id": nid, "block": self.ident()}
        if k == 1:
            node = {
                "type": "branch",
                "id": nid,
                "if": self.expr(1),
                "then": [self.flow_node(depth + 1) for _ in range(r.randrange(3))],
            }
            if r.random() < 0.5:
                node["else"] = [self.flow_node(depth + 1) for _ in range(r.randrange(3))]
            return node
        if k == 2:
            node = {
                "type": "randomiser",
                "id": nid,
                "children": [self.flow_node(depth + 1) for _ in range(r.randrange(4))],
            }
            if r.random() < 0.5:
                node["pick"] = r.choice([0, 1, 2, 5])
            return node
        if k == 3:
            return {
                "type": "assign",
                "id": nid,
                "variables": [self.ident() for _ in range(r.randrange(3))],
            }
        if k == 4:
            return {"type": "quotaCheck", "id": nid, "quota": self.ident()}
        if k == 5:
            node = {"type": "end", "id": nid}
            if r.random() < 0.5:
                node["outcome"] = r.choice(["complete", "screened", "declined", "1x"])
            if r.random() < 0.5:
                node["message"] = self.text()
            return node
        if k == 6:
            params = {
                r.choice(["a", "b", "pid", "osp_token"]): self.param_value()
                for _ in range(r.randrange(3))
            }
            return {
                "type": "externalTask",
                "id": nid,
                "template": r.choice(["t1", "t2", "nope"]),
                "params": params,
                "returns": [self.ident() for _ in range(r.randrange(3))],
            }
        return r.choice([{"type": "zz", "id": nid}, {"id": nid}, {"type": "block"}, 3])

    def param_value(self) -> Any:
        r = self.r
        return r.choice(
            [
                "abc",
                "a b",
                ".",
                "..",
                "x" * 70,
                "123",
                "${" + self.ident() + "}",
                "${$response.id}",
                "${$session.id}-x",
                "${ nope }",
                5,
                "x" * 257,
            ]
        )

    def template(self) -> Any:
        r = self.r
        url = r.choice(URLS)
        names = [n for n in ("a", "b", "pid", "osp_token") if "{" + n + "}" in url]
        if r.random() < 0.2:
            names = names[:-1] if names else ["zz"]
        params = {n: ({"pattern": r.choice(PATTERNS)} if r.random() < 0.5 else {}) for n in names}
        return {"url": url, "params": params}

    def question(self) -> Any:
        r = self.r
        qtype = r.choice(
            ["integer", "decimal", "text", "single", "multi", "date", "matrix", "slider", "note"]
        )
        q: dict[str, Any] = {"id": self.ident(), "type": qtype, "label": self.text()}
        if qtype in ("single", "multi", "matrix"):
            if r.random() < 0.6:
                q["choices"] = self.choices()
            if r.random() < 0.5:
                q["choiceList"] = self.ident()
        if qtype == "matrix":
            q["rows"] = [
                {
                    "id": r.choice(["r1", "r2", "R1", "x" * 60]),
                    "label": "row",
                    **({"required": r.choice([True, False, None])} if r.random() < 0.3 else {}),
                }
                for _ in range(r.randrange(4))
            ]
            if r.random() < 0.3:
                q["name"] = self.ident()
        if qtype in ("integer", "decimal"):
            for key in ("min", "max"):
                if r.random() < 0.5:
                    q[key] = r.choice(
                        [0, 5, -3, 10**15, "1.5", "-2.25", "1e5", "١٢", "0.0", "1" * 29, "x"]
                    )
        if qtype == "slider":
            q["valueType"] = r.choice(["integer", "decimal", "float"])
            for key in ("min", "max", "step"):
                if r.random() < 0.6:
                    q[key] = r.choice(
                        [
                            0,
                            1,
                            3,
                            10,
                            100,
                            -5,
                            "0.5",
                            "0.25",
                            "2.5",
                            "0",
                            "-1",
                            "1" * 28,
                            "0." + "0" * 26 + "1",
                            "1" * 20,
                            7,
                        ]
                    )
            for key in ("minLabel", "maxLabel"):
                if r.random() < 0.3:
                    q[key] = self.text()
        if qtype != "note" and r.random() < 0.3:
            q["name"] = self.ident()
        if r.random() < 0.3:
            q["showIf"] = self.expr(1)
        if qtype not in ("note", "matrix") and r.random() < 0.2:
            q["constraint"] = self.expr(1)
            if r.random() < 0.5:
                q["constraintMessage"] = self.text()
        if r.random() < 0.15:
            q["help"] = self.text()
        if r.random() < 0.05:
            q["custom"] = {
                r.choice(["construct", "Bad", "x1"]): r.choice(["a", 1, 2.5, True, None])
            }
        return q

    def choices(self) -> Any:
        r = self.r
        vals = r.sample([1, 2, 3, "a", "b", "a b", "", "1", 2, " x"], r.randrange(1, 5))
        return [{"value": v, "label": self.text() if r.random() < 0.2 else f"L{v}"} for v in vals]

    def variable(self) -> Any:
        r = self.r
        k = r.randrange(3)
        v: dict[str, Any] = {"id": self.ident()}
        if r.random() < 0.3:
            v["name"] = self.ident()
        if k == 0:
            v.update(kind="embedded", param="p", valueType=r.choice(["text", "integer", "decimal"]))
            if r.random() < 0.6:
                v["default"] = r.choice(
                    ["abc", 5, "1.5", "1e3", "Infinity", "NaN", " 2 ", "1_0", "x", "١"]
                )
        elif k == 1:
            v.update(kind="assigned", levels=r.sample([1, 2, "a", "b", "1", 1], r.randrange(1, 4)))
        else:
            v.update(kind="computed", expr=self.expr(1))
        return v

    def ending(self) -> Any:
        r = self.r
        e: dict[str, Any] = {}
        if r.random() < 0.5:
            e["title"] = self.text()
        if r.random() < 0.5:
            e["body"] = self.text()
        if r.random() < 0.3:
            e["summary"] = r.choice(["answers", "none", "x"])
        if r.random() < 0.6:
            red: dict[str, Any] = {"template": r.choice(["t1", "t2", "nope", "h1"])}
            if r.random() < 0.8:
                red["params"] = {
                    r.choice(["a", "b", "pid"]): self.param_value() for _ in range(r.randrange(3))
                }
            if r.random() < 0.5:
                red["delay"] = r.choice([0, 5, 61])
            if r.random() < 0.5:
                red["mode"] = r.choice(["auto", "link"])
            if r.random() < 0.2:
                red["label"] = self.text()
            e["redirect"] = red
        return e

    def hooks(self) -> Any:
        r = self.r
        h: dict[str, Any] = {"format": "osp-hooks/1", "source": "osp.on('onStart', () => {})"}
        h["handlers"] = {
            r.choice(["onStart", "onSubmitted", "onAnswer", "onFoo"]): {
                "reads": [self.ident() for _ in range(r.randrange(3))],
                "writes": [self.ident() for _ in range(r.randrange(2))],
            }
            for _ in range(r.randrange(3))
        }
        if r.random() < 0.5:
            h["redirects"] = {r.choice(["h1", "t1"]): self.template()}
        if r.random() < 0.4:
            h["parent"] = {
                "origin": r.choice(
                    [
                        "https://lab.example.org",
                        "http://localhost:3000",
                        "http://x.org",
                        "https://x.org:443",
                        "https://X.org",
                        "https://x.org/",
                        "https://x.org\n",
                    ]
                ),
                "messages": r.choice([{}, {"m": {"type": "string"}}, {"m": {"type": "zz"}}]),
            }
        return h

    # operators: each mutates self.doc in place (or replaces it) and may fail silently
    def op_delete_key(self) -> None:
        cands = [(c, k) for c, k in self.nodes() if isinstance(c, dict)]
        if cands:
            c, k = self.pick(cands)
            del c[k]

    def op_retype(self) -> None:
        cands = self.nodes()
        if cands:
            c, k = self.pick(cands)
            c[k] = copy.deepcopy(self.pick(SCALARS))

    def op_list_edit(self) -> None:
        lists = [(c, k) for c, k in self.nodes() if isinstance(c[k], list) and c[k]]
        if not lists:
            return
        c, k = self.pick(lists)
        xs = c[k]
        m = self.r.randrange(3)
        if m == 0:
            xs.insert(self.r.randrange(len(xs) + 1), copy.deepcopy(self.pick(xs)))
        elif m == 1:
            xs.pop(self.r.randrange(len(xs)))
        else:
            i, j = self.r.randrange(len(xs)), self.r.randrange(len(xs))
            xs[i], xs[j] = xs[j], xs[i]

    def op_rename_id(self) -> None:
        cands = self.dicts(lambda d: isinstance(d.get("id"), str))
        if cands:
            d = self.pick(cands)
            d["id"] = self.r.choice([self.ident(), d["id"].upper(), d["id"] + "_x"])

    def op_retarget(self) -> None:
        cands = self.where(REF_KEYS) + [
            (c, "id") for c in self.dicts(lambda d: d.get("kind") == "ref")
        ]
        if cands:
            c, k = self.pick(cands)
            c[k] = self.ident()
        lists = self.where({"variables", "returns", "reads", "writes"})
        if lists and self.r.random() < 0.5:
            c, k = self.pick(lists)
            if isinstance(c[k], list):
                c[k].append(self.ident())

    def op_name(self) -> None:
        cands = self.dicts(
            lambda d: isinstance(d.get("type"), str) or isinstance(d.get("kind"), str)
        )
        if cands:
            d = self.pick(cands)
            base = self.pick(self.names + self.ids) or "q1"
            d["name"] = self.r.choice(
                [base, base.upper(), base.lower(), "SEED", "_x", "a__STATE", "Meta"]
            )

    def op_text(self) -> None:
        cands = self.where(TEXT_KEYS)
        if cands:
            c, k = self.pick(cands)
            c[k] = self.text()

    def op_pipe(self) -> None:
        cands = [(c, k) for c, k in self.where(TEXT_KEYS) if isinstance(c[k], str)]
        if cands:
            c, k = self.pick(cands)
            c[k] = c[k] + "${" + self.r.choice([self.ident(), *BUILTINS]) + "}"

    def op_expr(self) -> None:
        cands = self.where(EXPR_KEYS)
        qs = self.dicts(lambda d: isinstance(d.get("label"), (str, dict)) and "id" in d)
        if cands and self.r.random() < 0.6:
            c, k = self.pick(cands)
            c[k] = self.expr()
        elif qs:
            self.pick(qs)[self.r.choice(["showIf", "constraint"])] = self.expr()

    def op_extra_key(self) -> None:
        cands = self.dicts()
        if cands:
            self.pick(cands)[
                self.r.choice(["zzz", "Type", "if_", "else_", "class_", "1", "__proto__"])
            ] = 1

    def op_tag(self) -> None:
        cands = self.where({"type", "kind"})
        if cands:
            c, k = self.pick(cands)
            c[k] = self.r.choice(
                [
                    "integer",
                    "single",
                    "note",
                    "matrix",
                    "slider",
                    "branch",
                    "end",
                    "ref",
                    "and",
                    "if",
                    "p",
                    "h",
                    "ul",
                    "rich",
                    "embedded",
                    "computed",
                    "Block",
                    5,
                ]
            )

    def op_languages(self) -> None:
        s = self.survey()
        md = s.get("metadata") if s else None
        if not isinstance(md, dict):
            return
        m = self.r.randrange(4)
        if m == 0:
            md["languages"] = self.r.choice(
                [["en", "fr"], ["en", "en"], ["fr"], ["de", "en", "fr"], []]
            )
        elif m == 1:
            md["defaultLanguage"] = self.r.choice(["en", "fr", "zz"])
        elif m == 2:
            md["title"] = self.r.choice(
                [{"en": "T", "fr": "T"}, {"fr": "T"}, self.rich(), "T" * 600]
            )
        else:
            md["description"] = self.text()

    def op_add_question(self) -> None:
        pages = self.dicts(lambda d: isinstance(d.get("items"), list))
        if pages:
            items = self.pick(pages)["items"]
            items.insert(self.r.randrange(len(items) + 1), self.question())

    def op_add_flow(self) -> None:
        s = self.survey()
        if s is not None and isinstance(s.get("flow"), list):
            flow = s["flow"]
            flow.insert(self.r.randrange(len(flow) + 1), self.flow_node())

    def op_add_variable(self) -> None:
        s = self.survey()
        if s is not None:
            vs = s.setdefault("variables", [])
            if isinstance(vs, list):
                vs.append(self.variable())

    def op_quota(self) -> None:
        s = self.survey()
        if s is None:
            return
        qs = s.setdefault("quotas", [])
        if isinstance(qs, list):
            qs.append(
                {
                    "id": self.ident(),
                    "when": self.expr(1),
                    "limit": self.r.choice([0, 10, -1]),
                    "onFull": {
                        "outcome": self.r.choice(["full", "complete"]),
                        **({"block": self.ident()} if self.r.random() < 0.5 else {}),
                    },
                }
            )
            if self.r.random() < 0.7 and isinstance(s.get("flow"), list):
                s["flow"].insert(
                    0, {"type": "quotaCheck", "id": self.ident(), "quota": qs[-1]["id"]}
                )

    def op_choices(self) -> None:
        cands = self.dicts(lambda d: isinstance(d.get("choices"), list))
        if cands:
            d = self.pick(cands)
            if self.r.random() < 0.5:
                d["choices"] = self.choices()
            else:
                d["choices"].append(
                    {"value": self.r.choice([1, "1", "a", "", "a b", 2.5]), "label": "dup"}
                )

    def op_settings(self) -> None:
        s = self.survey()
        if s is None:
            return
        st = s.setdefault("settings", {})
        if not isinstance(st, dict):
            return
        m = self.r.randrange(5)
        if m == 0:
            st["retention"] = self.r.choice(
                [
                    {"kind": "days-after-close", "days": 30},
                    {"kind": "days-after-close"},
                    {"kind": "after-date", "until": "2027-02-29"},
                    {"kind": "after-date", "until": "2028-02-29"},
                    {"kind": "after-date", "until": "٢٠٢٧-٠١-٠١"},
                    {"kind": "indefinite", "days": 3},
                    {"kind": "after-date", "until": "2027-01-01", "days": 1},
                    {"kind": "x"},
                ]
            )
        elif m == 1:
            st["redirectTemplates"] = {
                n: self.template()
                for n in self.r.sample(["t1", "t2", "h1"], self.r.randrange(1, 3))
            }
        elif m == 2:
            st["endings"] = {
                o: self.ending()
                for o in self.r.sample(
                    ["complete", "screened", "declined", "hook-failed", "full", "1x", "nope"],
                    self.r.randrange(1, 4),
                )
            }
        elif m == 3:
            st["theme"] = self.r.choice(
                [
                    {"colours": {"light": {"accent": "#000000"}, "dark": 5}},
                    {
                        "colours": {
                            "light": {
                                k: "#123456"
                                for k in (
                                    "accent",
                                    "background",
                                    "surface",
                                    "text",
                                    "muted",
                                    "error",
                                    "focus",
                                )
                            },
                            "dark": {
                                k: "#abcdef"
                                for k in (
                                    "accent",
                                    "background",
                                    "surface",
                                    "text",
                                    "muted",
                                    "error",
                                    "focus",
                                )
                            },
                        },
                        "baseSize": self.r.choice([10, 16, 40, 16.5]),
                        "lineSpacing": self.r.choice([0.5, 1, 1.5, 3]),
                    },
                ]
            )
        else:
            st[self.r.choice(["backNavigation", "saveMode", "resumeExpiryDays", "localCopy"])] = (
                self.pick(SCALARS)
            )

    def op_consent(self) -> None:
        s = self.survey()
        if s is not None:
            c: dict[str, Any] = {"text": self.text()}
            if self.r.random() < 0.4:
                c["declineOutcome"] = self.r.choice(["declined", "complete", "no"])
            if self.r.random() < 0.3:
                c["agreeLabel"] = self.text()
            s["consent"] = c

    def op_hooks(self) -> None:
        s = self.survey()
        if s is not None:
            s["hooks"] = self.hooks()

    def op_weird_string(self) -> None:
        cands = [(c, k) for c, k in self.nodes() if isinstance(c[k], str)]
        if cands:
            c, k = self.pick(cands)
            w = self.pick(WEIRD_STRINGS)
            c[k] = self.r.choice([w, c[k] + w, w + c[k]])

    def op_weird_key(self) -> None:
        cands = [d for d in self.dicts() if d]
        if cands:
            d = self.pick(cands)
            old = self.pick(list(d))
            new = self.r.choice([*WEIRD_STRINGS, old.upper(), old + "_", "if", "else", "class"])
            if new not in d:
                d[new] = d.pop(old)

    def op_graft(self) -> None:
        cands = self.nodes()
        if cands:
            c, k = self.pick(cands)
            c[k] = random_json(self.r, 1)

    def op_version(self) -> None:
        s = self.survey()
        if s is not None:
            s["specVersion"] = self.r.choice(["osp-survey/0.2", 5, None, "x" * 50])

    OPS = [
        "op_delete_key",
        "op_retype",
        "op_list_edit",
        "op_rename_id",
        "op_retarget",
        "op_name",
        "op_text",
        "op_pipe",
        "op_expr",
        "op_extra_key",
        "op_tag",
        "op_languages",
        "op_add_question",
        "op_add_flow",
        "op_add_variable",
        "op_quota",
        "op_choices",
        "op_settings",
        "op_consent",
        "op_hooks",
        "op_weird_string",
        "op_weird_key",
        "op_graft",
        "op_version",
    ]
    WEIGHTS = [6, 6, 6, 6, 6, 4, 6, 4, 8, 3, 3, 3, 8, 8, 5, 4, 4, 8, 3, 4, 5, 3, 3, 0.5]

    def mutate(self, n: int) -> Any:
        for name in self.r.choices(self.OPS, weights=self.WEIGHTS, k=n):
            getattr(self, name)()
        return self.doc


def random_json(rng: random.Random, depth: int = 0) -> Any:
    keys = [
        "specVersion",
        "id",
        "type",
        "kind",
        "label",
        "items",
        "pages",
        "blocks",
        "flow",
        "then",
        "else",
        "if",
        "children",
        "pick",
        "choices",
        "choiceList",
        "value",
        "metadata",
        "languages",
        "showIf",
        "levels",
        "expr",
        "name",
        "en",
        "op",
        "args",
        "ref",
        "x",
    ]
    tags = [
        "osp-survey/0.1",
        "integer",
        "single",
        "note",
        "block",
        "branch",
        "${q1}",
        "q1",
        "ref",
        "int",
        "and",
        "compare",
        "==",
        "rich",
        "p",
    ]
    k = rng.random()
    if depth > 3 or k < 0.4:
        return rng.choice([None, True, False, 0, 3, -7, 1.5, "", "abc", *tags])
    if k < 0.65:
        return [random_json(rng, depth + 1) for _ in range(rng.randrange(4))]
    return {rng.choice(keys): random_json(rng, depth + 1) for _ in range(rng.randrange(5))}


def edge_cases() -> list[Any]:
    """Hand-picked documents for paths random mutation rarely reaches."""
    base = {
        "specVersion": "osp-survey/0.1",
        "id": "s",
        "metadata": {"title": "T", "languages": ["en"]},
        "blocks": [
            {
                "id": "b",
                "pages": [
                    {
                        "id": "p",
                        "items": [
                            {
                                "id": "q1",
                                "type": "single",
                                "label": "Q",
                                "choices": [{"value": 1, "label": "a"}],
                            }
                        ],
                    }
                ],
            }
        ],
        "flow": [{"type": "block", "id": "n1", "block": "b"}],
    }
    out: list[Any] = []

    def with_(**kw: Any) -> None:
        d = copy.deepcopy(base)
        d.update(kw)
        out.append(d)

    origins = [
        "https://x.org:\u0664\u0664\u0663",
        "https://x.org:\u0668\u0660",
        "https://x.org:65536",
        "http://localhost:80",
        "http://127.0.0.1:8080",
        "https://[::1]",
        "https://x.org\n",
        "https://x.org\n\n",
        "https://a-b.c-d.org:1",
        "HTTPS://x.org",
    ]
    for o in origins:
        with_(
            hooks={
                "format": "osp-hooks/1",
                "source": "",
                "handlers": {},
                "parent": {"origin": o, "messages": {}},
            }
        )
    urls = [
        "https://x.org:\u0664\u0664\u0663/{a}",
        "https://x.org:8080/{a}",
        "https://X.ORG/{a}",
        "https://x.org/{a}\n",
        "https://x.org/\u00a0{a}",
        "https://x.org/\x1c{a}",
        "https://x.org{a}/",
        "https://x.org/{a}{a}",
        "https://x.org/{" + "a" * 32 + "}",
        "https://x.org/{1a}",
    ]
    pats = [
        "\\d+",
        "[\\d]+",
        "\\w+",
        "\\s*x",
        "\\S+",
        "(?i)abc",
        "(?>a)",
        "a++",
        "a{3",
        "a{,}",
        "a{}",
        "[]a]",
        "[^]a]",
        "\\-x",
        "a/b",
        "\\Aabc\\Z",
        "(?P<x>a)",
        "[a-z",
        "\\",
        "a{2}{3}",
        "(?#c)a",
        "\\x41",
        "\\u0041",
        "\\p{L}",
        "\\b",
        "[\\b]",
        "\\0",
        "\\1(a)",
    ]
    values = [
        "abc",
        "\u0661\u0662",
        "x y",
        "ABC",
        "a" * 65,
        "",
        "\n",
        "abc\n",
        "a/b",
        "--",
        "_",
        "ǅ",
        "٣",
    ]
    for u in urls:
        names = [n for n in ("a", "1a", "a" * 32) if "{" + n + "}" in u] or ["a"]
        with_(settings={"redirectTemplates": {"t": {"url": u, "params": {n: {} for n in names}}}})
    for i, pat in enumerate(pats):
        st = {
            "redirectTemplates": {
                "t": {"url": "https://x.org/r/{a}", "params": {"a": {"pattern": pat}}}
            },
            "endings": {
                "complete": {
                    "redirect": {"template": "t", "params": {"a": values[i % len(values)]}}
                },
                "declined": {
                    "redirect": {"template": "t", "params": {"a": values[(i + 3) % len(values)]}}
                },
            },
        }
        with_(settings=st)
        for v in values:
            ext = {"type": "externalTask", "id": "x", "template": "t", "params": {"a": v}}
            with_(
                settings={"redirectTemplates": st["redirectTemplates"]}, flow=[*base["flow"], ext]
            )
    for tag in [1.5, 2.5e-7, 1e-5, 0.0001, 123456789.125, -0.5, [1, "a'b", None], {"k": True}]:
        with_(flow=[{"type": tag, "id": "n"}])
    for v in [
        "it's",
        'a"b',
        "a'\"b",
        "\x00",
        "\ud83d\ude00",
        "\u0085",
        "\ufeff",
        "é\u0301",
        "\U0001f600",
    ]:
        with_(
            variables=[
                {"kind": "embedded", "id": "v", "param": "p", "valueType": "integer", "default": v},
                {"kind": "assigned", "id": "w", "levels": [v, v]},
            ]
        )
        d = copy.deepcopy(base)
        d["blocks"][0]["pages"][0]["items"][0]["choices"] = [
            {"value": v, "label": "a"},
            {"value": v, "label": "b"},
        ]
        d["blocks"][0]["pages"][0]["items"].append(
            {
                "id": "q2",
                "type": "integer",
                "label": "x",
                "showIf": {
                    "kind": "compare",
                    "op": "==",
                    "left": {"kind": "ref", "id": "q1"},
                    "right": {"kind": "text", "value": v},
                },
            }
        )
        out.append(d)
    for lo, hi, step in [
        ("0", "1", "0.1"),
        ("1" * 28, "0.5", "1"),
        ("-" + "9" * 27, "9" * 28, "0.0000001"),
        (0, 10**15, "0." + "0" * 26 + "1"),
        ("1", "1.0000000000000000000000000001", "0.5"),
        ("0.0", "-0", "1"),
        ("1E2", "200", "50"),
    ]:
        for vt in ("integer", "decimal"):
            d = copy.deepcopy(base)
            d["blocks"][0]["pages"][0]["items"].append(
                {
                    "id": "s1",
                    "type": "slider",
                    "label": "x",
                    "valueType": vt,
                    "min": lo,
                    "max": hi,
                    "step": step,
                }
            )
            out.append(d)
    for default in [
        "1_000",
        " 5 ",
        "\u20005",
        "_",
        "1e",
        "١٫٥",
        "+.5e-3",
        "infinity",
        "-sNaN12",
        "nan_1",
        "1__",
    ]:
        with_(
            variables=[
                {
                    "kind": "embedded",
                    "id": "v",
                    "param": "p",
                    "valueType": "decimal",
                    "default": default,
                }
            ]
        )
    # Python `re` patterns (redirect params): validity and full matches against many values.
    regexes = [
        "",
        "a",
        "abc",
        "a|b",
        "(a|b)+",
        "a*",
        "a+?",
        "a*+",
        "a++b",
        "(?:ab)++",
        "a{2}+",
        "a?+",
        "(?>a+)b",
        "(?>a|ab)c",
        "(?=a)a",
        "(?!b).",
        "(?<=a)b",
        "(?<!a)b",
        "(a)\\1",
        "\\1",
        "(a)\\2",
        "(a\\1)",
        "(?P<n>a)(?P=n)",
        "(?P<n>a)(?P<n>b)",
        "(?P=n)",
        "(?P<1>a)",
        "(?P<é>a)",
        "(?#x)a",
        "a(?#x)*",
        "a**",
        "*a",
        "+",
        "?",
        "a{2,1}",
        "a{1,2}",
        "a{,2}",
        "a{2,}",
        "a{}",
        "a{x}",
        "{1}",
        "x{",
        "}",
        "]",
        "[",
        "[]",
        "[]]",
        "[]a]",
        "[^]a]",
        "[a-]",
        "[-a]",
        "[z-a]",
        "[\\d-z]",
        "[a\\-z]",
        "[\\w]+",
        "[\\W]",
        "[\\S]",
        "[\\D]",
        "[\\s]",
        "[[a]",
        "[a&&b]",
        "[a--b]",
        "[a||b]",
        "[a~~b]",
        "\\d+",
        "\\D",
        "\\w+",
        "\\W",
        "\\s",
        "\\S+",
        "\\bab\\b",
        "a\\B",
        ".",
        ".+",
        "a$",
        "^a",
        "a\\Z",
        "\\Aa",
        "$a",
        "a$$",
        "\\x41",
        "\\x4",
        "\\u0041",
        "\\u004",
        "\\U00000041",
        "\\U00110000",
        "\\0",
        "\\01",
        "\\012",
        "\\101",
        "\\400",
        "\\8",
        "[\\8]",
        "[\\1]",
        "[\\101]",
        "\\a",
        "\\e",
        "\\q",
        "\\p{L}",
        "\\k<n>",
        "\\-",
        "\\/",
        "a/b",
        "\\.",
        "\\é",
        "(?i:abc)",
        "(?i)abc",
        "(?s:.)",
        "(?m:a$)",
        "(?x: a )",
        "(?a:\\w)",
        "(?u:a)",
        "(?L:a)",
        "(?-i:a)",
        "(?i-s:a)",
        "(?q)",
        "(?",
        "(",
        ")",
        "a)",
        "(a",
        "a)(b",
        "(?:",
        "(?P",
        "(?<a>b)",
        "(?(1)a|b)",
        "\\",
        "a\\",
        "[a-z]{1,64}",
        "[A-Za-z0-9_-]{1,64}",
        "[0-9]{3}-[0-9]{4}",
        "\\d{1,3}(\\.\\d+)?",
        "(?s:a.b)",
        "(?m:^a$)",
        "(?x:a b # c\n)",
        "(?x:a\\ b)",
        "(?x:[ ])",
        "(?a:\\d)",
        "(?a:\\s)",
        "(?a:\\bx)",
        "(?u:\\w)",
        "(?au:a)",
        "(?-a:a)",
        "(?i-i:a)",
        "(?ii:a)",
        "(?-:a)",
        "(?i:A(?-i:b))",
        "(?s:(?-s:.))",
        "(?x:a (?-x: ) b)",
        "(?m:a$)\\n?",
        "(?i:[a-z]+)",
        "(?i:é)",
        "x{99999999999}",
        "x{4294967294}",
        "x{4294967295}",
        "é+",
        "😀",
        "[😀-😂]",
        "\\ud83d",
    ]
    probes = [
        "",
        "a",
        "aa",
        "ab",
        "abc",
        "ABC",
        "b",
        "aab",
        "ac",
        "abab",
        "x",
        "xx",
        "1",
        "123",
        "١٢٣",
        "٣",
        "a b",
        " ",
        "\t",
        "\n",
        "a\n",
        "_",
        "é",
        "ǅ",
        "😀",
        "😁",
        "-",
        "a-",
        "A",
        ".",
        "/",
        "a/b",
        "555-1234",
        "1.5",
        "]",
        "]a",
        "^",
        "{",
        "}",
        "x{",
        "A1_-",
    ]
    for pat in regexes:
        st = {
            "redirectTemplates": {
                "t": {"url": "https://x.org/r/{a}", "params": {"a": {"pattern": pat}}}
            },
            "endings": {
                f"o{k}": {"redirect": {"template": "t", "params": {"a": v}}}
                for k, v in enumerate(probes)
            },
        }
        with_(settings=st)
    for until in [
        "2024-02-29",
        "2023-02-29",
        "1900-02-29",
        "2000-02-29",
        "0001-01-01",
        "9999-12-31",
        "2024-04-31",
    ]:
        with_(settings={"retention": {"kind": "after-date", "until": until}})
    return out


# --- Build -----------------------------------------------------------------------------------


def diagnostics(doc: Any) -> list[dict[str, str]]:
    return [d.model_dump() for d in validate(doc)]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    named: list[tuple[str, Any]] = []
    fixtures = sorted((ROOT / "fixtures").glob("*/survey.json"))
    for p in fixtures:
        named.append((f"fixture/{p.parent.name}", json.loads(p.read_text(encoding="utf-8"))))
    cases = sorted((ROOT / "python" / "osp-spec" / "tests" / "cases").glob("*/*.json"))
    for p in cases:
        named.append(
            (f"case/{p.parent.name}/{p.stem}", json.loads(p.read_text(encoding="utf-8"))["survey"])
        )
    for i, doc in enumerate(json.loads(HARVEST.read_text(encoding="utf-8"))):
        named.append((f"spec-test/{i}", doc))

    bases = [doc for name, doc in named if name.startswith(("fixture/", "case/valid/"))]
    rng = random.Random(SEED)
    for i in range(MUTANTS):
        base = bases[i % len(bases)]
        doc = Mutator(rng, copy.deepcopy(base)).mutate(rng.choice([1, 1, 2, 2, 3, 4, 6]))
        named.append((f"mutant/{i}", doc))
    for i, doc in enumerate(edge_cases()):
        named.append((f"edge/{i}", doc))
    for i in range(RANDOM_JSON):
        named.append((f"random/{i}", random_json(rng)))

    vectors = []
    skipped = 0
    seen: set[str] = set()
    codes: dict[str, int] = {}
    for name, doc in named:
        if not js_safe(doc):
            skipped += 1
            continue
        doc = js_order(doc)
        text = json.dumps(doc, ensure_ascii=True)
        if text in seen:
            continue
        seen.add(text)
        diags = diagnostics(doc)
        for d in diags:
            codes[d["code"]] = codes.get(d["code"], 0) + 1
        vectors.append({"name": name, "doc": doc, "diagnostics": diags})
    (OUT / "vectors.json").write_text(json.dumps(vectors, ensure_ascii=True), encoding="utf-8")
    never = sorted(
        set(CODES) - set(codes) - {"publish.retention_required", "publish.consent_missing"}
    )
    print(
        f"spec vectors: {len(vectors)} documents ({skipped} not JavaScript-safe skipped), "
        f"{sum(codes.values())} diagnostics, {len(codes)} codes; "
        f"never emitted: {', '.join(never) or 'none'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
