"""Expression text-syntax parity vectors for web/engine/src/syntax.ts (task CE1).

    uv run python web/engine/scripts/build_syntax_vectors.py

Writes `web/engine/.build/syntax.json` (gitignored), read by test/syntax-parity.test.ts:

- ``print``: ``[ast, text]``: `osp_expr.to_text` of every expression in every fixture survey,
  every AST the python/osp-expr tests print, and random ASTs (unicode and escaped text,
  big integers, exotic decimals, keyword-like ids, deep nesting).
- ``parse``: ``[source, result]``: `osp_expr.parse` of every printed text, every source the
  python/osp-expr tests parse, and generated strings: whitespace variants, token
  mutations (deletions, insertions of hostile characters, swaps, truncations) and
  hand-written edge cases. ``result`` is ``{"expr": <plan JSON> | null, "text": <to_text> |
  null, "diagnostics": [[code, message, start, end], ...]}``.

The test sources are recorded by running python/osp-expr's tests in-process with `parse`
and `to_text` wrapped (about a second).
"""

from __future__ import annotations

import json
import random
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import osp_expr
import osp_expr.syntax as syntax
import pytest
from osp_expr import EXPR_ADAPTER
from osp_runtime.plan import expr_json

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures"
OUT = ROOT / "web" / "engine" / ".build"
EXPR_KINDS = {
    "int", "decimal", "text", "bool", "null", "ref", "compare", "arith",
    "and", "or", "not", "answered", "contains", "if",
}  # fmt: skip

_parse = syntax.parse
_to_text = syntax.to_text


def parse_row(src: Any) -> list:
    res = _parse(src)
    expr = expr_json(res.expr) if res.expr is not None else None
    return [
        src,
        {
            "expr": expr,
            "text": _to_text(res.expr) if res.expr is not None else None,
            "diagnostics": [[d.code, d.message, d.start, d.end] for d in res.diagnostics],
        },
    ]


# --- Sources ----------------------------------------------------------------------


def fixture_exprs() -> list:
    found: list = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("kind") in EXPR_KINDS:
                try:
                    found.append(EXPR_ADAPTER.validate_python(node))
                    return
                except Exception:
                    pass
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for f in sorted(FIXTURES.iterdir()):
        if (f / "survey.json").is_file():
            walk(json.loads((f / "survey.json").read_text()))
    return found


def test_cases() -> tuple[list, list]:
    """Every parse() source and to_text() AST in python/osp-expr's tests."""
    sources: list = []
    printed: list = []

    def rec_parse(src):
        sources.append(src)
        return _parse(src)

    def rec_print(expr):
        printed.append(expr)
        return _to_text(expr)

    patched = [(osp_expr, "parse", rec_parse), (syntax, "parse", rec_parse)]
    patched += [(osp_expr, "to_text", rec_print), (syntax, "to_text", rec_print)]
    for mod, name, fn in patched:
        setattr(mod, name, fn)
    try:
        args = [str(ROOT / "python" / "osp-expr" / "tests"), "-q", "-p", "no:cacheprovider"]
        code = pytest.main([*args, "--hypothesis-seed=20261018", "-o", "addopts="])
    finally:
        originals = {"parse": _parse, "to_text": _to_text}
        for mod, name, _ in patched:
            setattr(mod, name, originals[name])
    if code != 0:
        raise SystemExit(f"python/osp-expr tests failed ({code}); no syntax vectors written")
    return sources, printed


# --- Random ASTs ------------------------------------------------------------------

IDS = ["q1", "q3", "age", "_x", "Q_2b", "andy", "notes", "orbit", "nullable", "trueish",
       "answered", "contains", "if", "if_", "x" * 40, "a1b2c3", "A"]  # fmt: skip
TEXT_CHARS = list('ab Z09"\\\n\r\t\x00\x01\x1f\x7f\x80\x85\xa0éß日本😀​ 　﻿́') + [
    "\U000e0001",
    "\U0001f600",
    "'",
    "$",
    "{",
    "}",
]


def rand_text(r: random.Random) -> str:
    return "".join(r.choice(TEXT_CHARS) for _ in range(r.randint(0, 8)))


def rand_decimal(r: random.Random) -> str:
    roll = r.random()
    if roll < 0.3:
        return r.choice(["0.1", "2.50", "-0.0", "0.000", "1E+3", "-1E-7", "0E-7", "0E+5", "-0", "1.5E+3",
                         "0.0000001", "0.000001", "123456789012345678901234567890.5", "1E-30", "-7.25"])  # fmt: skip
    digits = "".join(r.choice("0123456789") for _ in range(r.randint(1, 30)))
    sign = "-" if r.random() < 0.3 else ""
    return str(Decimal(f"{sign}{digits}E{r.randint(-35, 12)}"))


def rand_int(r: random.Random) -> int:
    roll = r.random()
    if roll < 0.5:
        return r.choice([0, 1, 2, 7, 10, -1, -3, 2**53 - 1, 2**53, -(2**53 - 1), -(2**53), 1000])
    return r.randint(-(10 ** r.randint(1, 60)), 10 ** r.randint(1, 60))


def rand_leaf(r: random.Random) -> dict:
    roll = r.random()
    if roll < 0.35:
        return {"kind": "ref", "id": r.choice(IDS)}
    if roll < 0.55:
        return {"kind": "int", "value": rand_int(r)}
    if roll < 0.7:
        return {"kind": "decimal", "value": rand_decimal(r)}
    if roll < 0.88:
        return {"kind": "text", "value": rand_text(r)}
    if roll < 0.95:
        return {"kind": "bool", "value": r.random() < 0.5}
    return {"kind": "null"}


def rand_ast(r: random.Random, depth: int) -> dict:
    if depth <= 0 or r.random() < 0.2:
        return rand_leaf(r)
    sub = lambda: rand_ast(r, depth - 1)  # noqa: E731
    roll = r.random()
    if roll < 0.25:
        return {"kind": "arith", "op": r.choice("+-*/"), "left": sub(), "right": sub()}
    if roll < 0.45:
        op = r.choice(["==", "!=", "<", "<=", ">", ">="])
        return {"kind": "compare", "op": op, "left": sub(), "right": sub()}
    if roll < 0.62:
        return {"kind": r.choice(["and", "or"]), "args": [sub() for _ in range(r.randint(2, 4))]}
    if roll < 0.72:
        return {"kind": "not", "arg": sub()}
    if roll < 0.8:
        return {"kind": "if", "cond": sub(), "then": sub(), "else": sub()}
    ref = {"kind": "ref", "id": r.choice(IDS)}
    if roll < 0.88:
        return {"kind": "answered", "ref": ref}
    return {"kind": "contains", "ref": ref, "value": sub()}


def deep_ast(r: random.Random, depth: int) -> dict:
    """A chain of nested nodes around MAX_DEPTH, so the printed text hits too-deep or not."""
    node = (
        rand_leaf(r)
        if r.random() < 0.5
        else {"kind": "answered", "ref": {"kind": "ref", "id": "q1"}}
    )
    for _ in range(depth):
        k = r.choice(["not", "arith", "and", "contains", "if", "compare"])
        if k == "not":
            node = {"kind": "not", "arg": node}
        elif k == "arith":
            node = {"kind": "arith", "op": r.choice("+-*/"), "left": rand_leaf(r), "right": node}
        elif k == "and":
            node = {"kind": "and", "args": [node, rand_leaf(r)]}
        elif k == "contains":
            node = {"kind": "contains", "ref": {"kind": "ref", "id": "q1"}, "value": node}
        elif k == "compare":
            node = {"kind": "compare", "op": "==", "left": node, "right": rand_leaf(r)}
        else:
            node = {"kind": "if", "cond": rand_leaf(r), "then": node, "else": rand_leaf(r)}
    return node


# --- Generated strings ------------------------------------------------------------

INSERTS = list("=!&|'#\\\".,;()+-*/<>_0123456789aZ \t\n") + [
    "&&", "||", "==", "!=", "<=", ">=", "and", "or", "not", "null", "true", "false", "if(",
    "answered(", "contains(", "foo(", "\\u", "\\u00", "\\u12g4", "\\x", "1.", ".5", "1e5",
    "\xa0", "​", "　", "﻿", " ", "\x00", "\x7f", "\x85", "\xad", "é", "日",
    "😀", "\U000e0001", "", "́", "͸", "\ud800", "$", "${q1}", "{", "`", "@", "~",
]  # fmt: skip

EDGE = [
    "", " ", "\t\n", "(", ")", "()", "q1", "-", "--1", "- -1", "-1.5", "-0", "-0.0", "1.", "1..2", "1.2.3",
    "00.10", "0.0000000", "1e3", "1_000", "x == 1.", '"', '"\\', '"\\u', '"\\u12', '"\\u12345"', '"\\uD83D\\uDE00"',
    '"\\u00e9"', '"\\U0001F600"', '"\\a"', "'a'", "a = 1", "a ! b", "!a", "a & b", "a | b", "a <> b",
    "a === b", "a => b", "a =< b", "1 < 2 < 3", "a == b == c", "not", "not not", "and", "a and", "or b",
    "answered()", "answered(q1", "answered(q1, q2)", "answered(1)", 'answered("q1")', "contains(q1)",
    "contains(q1,)", "contains(1, 2)", "contains(q1, 2", "if()", "if(a)", "if(a, b)", "if(a, b, c, d)",
    "if(a, b, c", "if (a, b, c)", "IF(a, b, c)", "true(1)", "null(1)", "x(1)", "q1 q2", "q1 (q2)",
    "(q1) q2", "1 2", "a.b", "a..b", "1a", "9" * 1000 + " == a", "9" * 1001, "0" * 1001,
    "1" + "0" * 999 + ".5", "-" + "9" * 1000, "(" * 64 + "a" + ")" * 64, "(" * 65 + "a" + ")" * 65,
    "not " * 64 + "a", "not " * 65 + "a", " + ".join(["a"] * 64), " + ".join(["a"] * 65),
    " and ".join(["a"] * 200), "if(" * 40 + "a" + ", b, c)" * 40, "contains(q1, " * 70 + "1" + ")" * 70,
    "-q1", "- (1)", "-null", "a - - 1", "a * -", "é == 1", "q1 == 😀", '"😀" == q1', "q1 == 1",
]  # fmt: skip


def tokens(text: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == '"':
            j = i + 1
            while j < len(text) and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif text[i] == " ":
            i += 1
        else:
            j = i + 1
            while (
                j < len(text)
                and text[j] not in ' "()'
                and text[i] not in "()"
                and text[j].isalnum() == text[i].isalnum()
            ):
                j += 1
            out.append(text[i:j])
            i = j
    return out


def whitespace_variant(r: random.Random, text: str) -> str:
    toks = tokens(text)
    seps = [r.choice(["", " ", "  ", "\n", "\t", " \r\n "]) for _ in toks]
    return r.choice(["", " ", "\n"]) + "".join(t + s for t, s in zip(toks, seps, strict=True))


def mutate(r: random.Random, text: str) -> str:
    roll = r.random()
    if not text:
        return r.choice(INSERTS)
    i = r.randrange(len(text) + 1)
    if roll < 0.25:  # delete a character
        return text[:i] + text[i + 1 :]
    if roll < 0.55:  # insert something hostile
        return text[:i] + r.choice(INSERTS) + text[i:]
    if roll < 0.7:  # truncate
        return text[:i]
    toks = tokens(text)
    if len(toks) < 2:
        return text + r.choice(INSERTS)
    a, b = r.randrange(len(toks)), r.randrange(len(toks))
    if roll < 0.82:  # swap two tokens
        toks[a], toks[b] = toks[b], toks[a]
    elif roll < 0.92:  # duplicate a token
        toks.insert(a, toks[a])
    else:  # replace a token
        toks[a] = r.choice(INSERTS)
    return " ".join(toks)


def main() -> int:
    r = random.Random(20261018)
    test_sources, test_printed = test_cases()

    asts: list = [*fixture_exprs(), *test_printed]
    n_fixture = len(fixture_exprs())
    for _ in range(3000):
        asts.append(EXPR_ADAPTER.validate_python(rand_ast(r, r.randint(1, 5))))
    for _ in range(300):
        asts.append(EXPR_ADAPTER.validate_python(deep_ast(r, r.randint(58, 68))))

    prints: list = []
    texts: list[str] = []
    seen: set[str] = set()
    for e in asts:
        ast = expr_json(e)
        key = json.dumps(ast, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        text = _to_text(e)
        prints.append([ast, text])
        texts.append(text)

    sources: list = [*test_sources, *EDGE, *texts]
    for text in texts[: len(texts) // 2]:
        sources.append(whitespace_variant(r, text))
    for _ in range(4000):
        sources.append(mutate(r, r.choice(texts) if r.random() < 0.9 else r.choice(EDGE)))
    for _ in range(500):  # double mutations
        sources.append(mutate(r, mutate(r, r.choice(texts))))

    parses = []
    done: set = set()
    for s in sources:
        key = s if isinstance(s, str) else repr(s)
        if key in done:
            continue
        done.add(key)
        parses.append(parse_row(s))

    ok = sum(1 for _, res in parses if res["expr"] is not None)
    stats = {
        "fixtureExprs": n_fixture,
        "testSources": len(test_sources),
        "testPrinted": len(test_printed),
    }
    stats |= {
        "print": len(prints),
        "parse": len(parses),
        "parseOk": ok,
        "parseErrors": len(parses) - ok,
    }
    codes: dict[str, int] = {}
    for _, res in parses:
        for d in res["diagnostics"]:
            codes[d[0]] = codes.get(d[0], 0) + 1
    stats["errorCodes"] = dict(sorted(codes.items()))
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {"source": "osp_expr.syntax (web/engine/scripts/build_syntax_vectors.py)", "stats": stats}
    doc |= {"print": prints, "parse": parses}
    # ensure_ascii: sources may hold lone surrogates, which UTF-8 cannot carry.
    (OUT / "syntax.json").write_text(json.dumps(doc))
    print(
        f"syntax vectors: {len(prints)} print, {len(parses)} parse ({ok} ok) in {OUT.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
