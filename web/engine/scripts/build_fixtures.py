"""Build inputs for the engine tests into web/engine/.build/ (gitignored).

    uv run python web/engine/scripts/build_fixtures.py

1. Every fixture survey (`osp-survey/0.1`, converted by C3b) → runtime plan
   (`osp_runtime.plan`), as `.build/fixtures/<fixture>.plan.json`, plus
   `<fixture>.meta.json` (diagnostics). A survey with error diagnostics gets
   `{"error": ...}` instead of a plan.
2. Parity vectors (`.build/parity.json`): node_seed and randomize from
   `osp_engine.random` for 10,000 seeds, compared with the TS port by test/parity.test.ts.
3. Shared vectors (`test/vectors/shared.json`, committed): SHA-256, node_seed, randomize,
   assign and seed-error cases at the edges. Regenerated here into `.build/shared.json`;
   the TS tests check the committed file is current and that TS matches it.
4. Expression vectors (`.build/expr.json`): random ASTs and environments evaluated by
   `osp_expr.evaluate` (exact decimals, null rules, if(), codes as text), with the runtime
   diagnostics it reports, compared by test/expr-parity.test.ts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import datetime as dt
import hashlib
import random
from decimal import Decimal

from osp_engine.random import (
    MAX_SEED,
    NODE_SEED_MAX,
    RandomInputError,
    _permute,
    assign,
    node_seed,
    randomize,
)
from osp_expr import EXPR_ADAPTER, evaluate
from osp_runtime.plan import compile_survey, expr_json

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures"
OUT = ROOT / "web" / "engine" / ".build"


class BuildError(Exception):
    pass


def build_fixture(folder: Path) -> tuple[str, bool]:
    raw = json.loads((folder / "survey.json").read_text())
    meta: dict[str, Any] = {"fixture": folder.name, "specVersion": raw.get("specVersion")}
    try:
        plan, diags = compile_survey(raw)
        meta["diagnostics"] = [d.model_dump(mode="json") for d in diags]
        if plan is None:
            errors = [f"{d.code} {d.pointer}: {d.message}" for d in diags if d.severity == "error"]
            raise BuildError("osp-spec: " + " | ".join(errors))
        out: dict[str, Any] = plan
    except BuildError as e:
        out = {"error": f"{type(e).__name__}: {e}"}
    (OUT / "fixtures" / f"{folder.name}.plan.json").write_text(json.dumps(out, ensure_ascii=False))
    (OUT / "fixtures" / f"{folder.name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False))
    return folder.name, "error" not in out


def parity_vectors(n: int = 10_000) -> dict:
    """Seeds spread over 1 … 2^53 − 1 (deterministic), with boundary seeds first."""
    seeds = [1, 2, 3, NODE_SEED_MAX, NODE_SEED_MAX + 1, 2**31 - 1, 2**31, 2**32, MAX_SEED - 1, MAX_SEED]
    x = 0x9E3779B97F4A7C15
    while len(seeds) < n:
        x = (x * 6364136223846793005 + 1442695040888963407) % 2**64
        bits = 1 + (x >> 58) % 53  # spread magnitudes over 1 … 2^53
        seeds.append(1 + (x >> 7) % min(MAX_SEED, 2**bits))
    rows = []
    for i, s in enumerate(seeds):
        size = 1 + i % 26
        node = ["q1", "page_7", "r_blocks", "é✓", "x" * (i % 40)][i % 5]
        version = ["1", "3", "draft", "12345678901234567890", ""][i // 5 % 5]
        ns = node_seed(version, s, node)
        rows.append([s, version, node, ns, randomize(range(size), s), randomize(range(size), ns)])
    return {"source": "osp_engine.random (python/osp-engine)", "rows": rows}


def _code(fn) -> object:
    try:
        return fn()
    except RandomInputError as e:
        return {"error": e.code}


def shared_vectors() -> dict:
    """Edge cases shared by Python and TS (semantics.md §7, runtime-design.md §4)."""
    seeds = [1, 2, 7, 16807, NODE_SEED_MAX, 2**31 - 1, 2**31, 2**32 - 1, 2**32, 2**52, MAX_SEED - 1]
    seeds.append(MAX_SEED)
    texts = ["", "a", "abc", "é", "日本語", "😀", "x" * 55, "x" * 56, "x" * 63, "x" * 64, "y" * 1000]
    sha = [[t, hashlib.sha256(t.encode()).hexdigest()] for t in texts]
    ids = ["q1", "", "r_blocks", "é✓", "😀", "a:b,c", "1:a,", "z" * 300]
    versions = ["1", "3", "draft", "", "1:2,", "日本"]
    node = []
    for s in seeds:
        for v in versions:
            for n in ids:
                node.append([v, s, n, node_seed(v, s, n)])
    perms = []
    for s in [*seeds, 0, -1, -(2**31), -MAX_SEED]:
        for size in (0, 1, 2, 3, 5, 26, 100):
            perms.append([s, size, _permute(list(range(size)), s)])
    assigns = []
    for s in seeds[:8]:
        for k in (1, 2, 3, 4, 7):
            assigns.append([s, k, None, assign(list(range(k)), None, s)])
        assigns.append([s, 3, [1, 0, 2], assign([0, 1, 2], [1, 0, 2], s)])
    bad_seeds = [[x, _code(lambda x=x: randomize([1], x))] for x in (0, -1, 2**53, 1.5)]
    bad_node = [_code(lambda: node_seed("1", 1, "\udfff")), _code(lambda: node_seed("\ud800", 1, "q"))]
    return {
        "source": "python/osp-engine osp_engine.random + hashlib (web/engine/scripts/build_fixtures.py)",
        "sha256": sha,
        "nodeSeed": node,
        "randomize": perms,
        "assign": assigns,
        "badSeeds": [[str(x), c] for x, c in bad_seeds],
        "badNodeSeed": bad_node,
    }


# --- Expression vectors --------------------------------------------------------------


def _rand_decimal(r: random.Random) -> Decimal:
    digits = "".join(r.choice("0123456789") for _ in range(r.randint(1, 34)))
    exp = r.randint(-30, 10)
    sign = "-" if r.random() < 0.3 else ""
    return Decimal(f"{sign}{digits}E{exp}")


def _rand_number(r: random.Random) -> int | Decimal:
    roll = r.random()
    if roll < 0.35:
        return r.choice([0, 1, 2, 3, 4, 7, 10, -1, -3, 1000])
    if roll < 0.5:
        return r.randint(-(10**30), 10**30)
    if roll < 0.75:
        return Decimal(r.choice(["0.1", "0.2", "0.3", "2.5", "0.5", "1.5", "-2.5", "3.0", "0.000"]))
    return _rand_decimal(r)


def _env_value(r: random.Random, kind: str):
    if r.random() < 0.15:
        return None
    if kind == "int":
        return r.choice([0, 1, 2, 5, 10, -4, 12345678901234, 2**53 - 1])
    if kind == "dec":
        return _rand_number(r) if r.random() < 0.5 else Decimal(r.choice(["0.1", "2.50", "-0.0", "1E+3"]))
    if kind == "text":
        return r.choice(["a", "b", " a ", "   ", "", "x y", "\u00a0b\u3000", "\ufeffc", "\x1cd"])
    if kind == "date":
        return dt.date(r.randint(1990, 2030), r.randint(1, 12), r.randint(1, 28))
    return frozenset(r.sample([1, 2, 3, "a", "b"], r.randint(0, 3)))


ENV_KINDS = {"i1": "int", "i2": "int", "d1": "dec", "d2": "dec", "t1": "text", "t2": "text"}
ENV_KINDS |= {"dt1": "date", "dt2": "date", "m1": "multi", "m2": "multi"}


def _rand_expr(r: random.Random, depth: int) -> dict:
    leaf = depth <= 0 or r.random() < 0.25
    if leaf:
        roll = r.random()
        if roll < 0.4:
            return {"kind": "ref", "id": r.choice([*ENV_KINDS, "missing"])}
        if roll < 0.75:
            n = _rand_number(r)
            if isinstance(n, int):
                return {"kind": "int", "value": n}
            return {"kind": "decimal", "value": str(n)}
        if roll < 0.9:
            return {"kind": "text", "value": r.choice(["a", "b", "x y", "1", "2", ""])}
        if roll < 0.95:
            return {"kind": "bool", "value": r.random() < 0.5}
        return {"kind": "null"}
    roll = r.random()
    sub = lambda: _rand_expr(r, depth - 1)  # noqa: E731
    if roll < 0.3:
        return {"kind": "arith", "op": r.choice("+-*/"), "left": sub(), "right": sub()}
    if roll < 0.55:
        op = r.choice(["==", "!=", "<", "<=", ">", ">="])
        return {"kind": "compare", "op": op, "left": sub(), "right": sub()}
    if roll < 0.65:
        return {"kind": r.choice(["and", "or"]), "args": [sub() for _ in range(r.randint(2, 3))]}
    if roll < 0.72:
        return {"kind": "not", "arg": sub()}
    if roll < 0.77:
        return {"kind": "if", "cond": sub(), "then": sub(), "else": sub()}
    ref = {"kind": "ref", "id": r.choice([*ENV_KINDS, "missing"])}
    if roll < 0.82:
        return {"kind": "answered", "ref": ref}
    value = r.choice([{"kind": "int", "value": r.choice([1, 2, 3])}, {"kind": "text", "value": "a"}])
    if r.random() < 0.2:
        value = sub()
    return {"kind": "contains", "ref": ref, "value": value}


def _json_env(v) -> object:
    if v is None:
        return None
    if isinstance(v, bool):
        raise AssertionError
    if isinstance(v, int):
        return {"t": "int", "v": str(v)}
    if isinstance(v, Decimal):
        return {"t": "dec", "v": str(v)}
    if isinstance(v, str):
        return {"t": "text", "v": v}
    if isinstance(v, dt.date):
        return {"t": "date", "v": v.isoformat()}
    return {"t": "multi", "v": sorted(v, key=str)}


def _json_result(v) -> object:
    if v is None:
        return None
    if isinstance(v, bool):
        return {"k": "bool", "v": v}
    if isinstance(v, int):
        return {"k": "num", "int": True, "v": str(v)}
    if isinstance(v, Decimal):
        return {"k": "num", "int": False, "v": str(v)}
    if isinstance(v, str):
        return {"k": "text", "v": v}
    if isinstance(v, dt.date):
        return {"k": "date", "v": v.isoformat()}
    return {"k": "multi", "v": sorted(v, key=str)}


def expr_vectors(n: int = 6000) -> dict:
    r = random.Random(20261016)
    rows = []
    while len(rows) < n:
        env = {k: _env_value(r, kind) for k, kind in ENV_KINDS.items()}
        ast = _rand_expr(r, r.randint(1, 4))
        expr = EXPR_ADAPTER.validate_python(ast)
        diags: list = []
        out = evaluate(expr, env, diags)
        rows.append(
            [
                expr_json(expr),
                {k: _json_env(v) for k, v in env.items()},
                _json_result(out),
                [[d.code, d.path] for d in diags],
            ]
        )
    return {"source": "osp_expr.evaluate", "rows": rows}


def main() -> int:
    (OUT / "fixtures").mkdir(parents=True, exist_ok=True)
    built = [build_fixture(f) for f in sorted(FIXTURES.iterdir()) if (f / "survey.json").is_file()]
    (OUT / "parity.json").write_text(json.dumps(parity_vectors()))
    (OUT / "shared.json").write_text(json.dumps(shared_vectors(), ensure_ascii=False, indent=1))
    (OUT / "expr.json").write_text(json.dumps(expr_vectors(), ensure_ascii=False))
    ok = sum(1 for _, good in built if good)
    print(f"engine fixtures: {ok}/{len(built)} plans built in {OUT.relative_to(ROOT)}")
    for name, good in built:
        if not good:
            print(f"  not built: {name} (see .build/fixtures/{name}.plan.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
