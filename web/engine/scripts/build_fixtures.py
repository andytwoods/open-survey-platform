"""Build inputs for the engine tests into web/engine/.build/ (gitignored).

    uv run python web/engine/scripts/build_fixtures.py

1. Every fixture survey → runtime plan (`osp_runtime.plan`), as
   `.build/fixtures/<fixture>.plan.json`, plus `<fixture>.meta.json` (diagnostics and an id
   map). Surveys already in `osp-survey/0.1` compile as they are. Surveys still in the
   provisional `osp-fixture-survey/0` format (fixtures/FORMAT.md; C3b converts them) are
   converted here first, mechanically:
     - v0 block `B` (one page) → osp block `b__B` with one page `B`, so traces keep `B`
       as the page id and as the itemOrder stream id (FORMAT.md §1);
     - v0 flow nodes get ids: `n_B` for a block node, `br<k>`, `as<k>`, `qc_<quota>`,
       `end<k>`; randomisers keep theirs. The id map lets the runner translate
       randomiser orders (child node ids) back to block ids;
     - choice list `L` → `cl_L` (v0 lists had their own namespace; osp ids are global);
     - `design.factors` → assigned variables; `embeddedData` → embedded variables;
       `calculate` items → computed variables. Text expressions are parsed by osp-expr.
   A fixture that does not validate or parse gets `{"error": ...}` instead of a plan.
2. Parity vectors (`.build/parity.json`): node_seed and randomize from
   `osp_engine.random` for 10,000 seeds, compared with the TS port by test/parity.test.ts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from osp_engine.random import MAX_SEED, NODE_SEED_MAX, node_seed, randomize
from osp_expr import parse as parse_expr
from osp_runtime.plan import compile_survey

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures"
OUT = ROOT / "web" / "engine" / ".build"


class ConvertError(Exception):
    pass


def _expr(src: str, where: str) -> dict:
    r = parse_expr(src)
    if r.expr is None:
        msgs = "; ".join(d.message for d in r.diagnostics)
        raise ConvertError(f"{where}: cannot parse {src!r}: {msgs}")
    return r.expr.model_dump(mode="json", by_alias=True)


def convert_v0(v0: dict) -> tuple[dict, dict]:
    """osp-fixture-survey/0 → (osp-survey/0.1, id map)."""
    nodes_map: dict[str, str] = {}
    counter = {"br": 0, "as": 0, "end": 0}
    factors = [f["id"] for f in v0.get("design", {}).get("factors", [])]
    variables: list[dict] = []
    for e in v0.get("embeddedData", []):
        var = {"kind": "embedded", "id": e["name"], "param": e["param"]}
        if "default" in e:
            var["default"] = e["default"]
        variables.append(var)
    computed: list[dict] = []

    def item(it: dict) -> dict | None:
        t = it["type"]
        if t == "calculate":
            expr = _expr(it["expr"], it["id"])
            computed.append({"kind": "computed", "id": it["id"], "expr": expr})
            return None
        out: dict[str, Any] = {"id": it["id"], "type": t, "label": it.get("label", it["id"])}
        if "showIf" in it:
            out["showIf"] = _expr(it["showIf"], it["id"])
        if t == "note":
            return out
        for k in ("required", "constraintMessage", "choiceOrder"):
            if k in it:
                out[k] = it[k]
        if "constraint" in it:
            out["constraint"] = _expr(it["constraint"], it["id"])
        if "choices" in it:
            out["choiceList"] = f"cl_{it['choices']}"
        return out

    blocks = []
    for bid, b in v0["blocks"].items():
        items = [x for x in (item(it) for it in b["items"]) if x is not None]
        page = {"id": bid, "items": items}
        if "itemOrder" in b:
            page["itemOrder"] = b["itemOrder"]
        blocks.append({"id": f"b__{bid}", "pages": [page]})

    def node(n: dict) -> dict:
        if "block" in n:
            nid = f"n_{n['block']}"
            nodes_map[nid] = n["block"]
            return {"type": "block", "id": nid, "block": f"b__{n['block']}"}
        if "branch" in n:
            counter["br"] += 1
            br = n["branch"]
            return {
                "type": "branch",
                "id": f"br{counter['br']}",
                "if": _expr(br["if"], "branch"),
                "then": [node(c) for c in br.get("then", [])],
                "else": [node(c) for c in br.get("else", [])],
            }
        if "randomiser" in n:
            r = n["randomiser"]
            return {"type": "randomiser", "id": r["id"], "children": [node(c) for c in r["shuffle"]]}
        if "assign" in n:
            counter["as"] += 1
            return {"type": "assign", "id": f"as{counter['as']}", "variables": factors}
        if "quotaCheck" in n:
            return {"type": "quotaCheck", "id": f"qc_{n['quotaCheck']}", "quota": n["quotaCheck"]}
        if "end" in n:
            counter["end"] += 1
            return {"type": "end", "id": f"end{counter['end']}", "outcome": n["end"]}
        raise ConvertError(f"unknown v0 flow node {n!r}")

    flow = [node(n) for n in v0["flow"]]
    for f in v0.get("design", {}).get("factors", []):
        variables.append({"kind": "assigned", "id": f["id"], "levels": f["levels"]})
    quotas = []
    for q in v0.get("quotas", []):
        goto = q.get("onFull", {}).get("goto")
        quotas.append(
            {
                "id": q["id"],
                "when": _expr(q["when"], q["id"]),
                "limit": q["limit"],
                # The v0 format has no outcome for a full quota (C3a-3); placeholder.
                "onFull": {"block": f"b__{goto}" if goto else None, "outcome": "quota_full"},
            }
        )
    survey = {
        "specVersion": "osp-survey/0.1",
        "id": v0["id"],
        "version": v0.get("version"),
        "metadata": {"title": v0["title"], "languages": v0["languages"]},
        "settings": v0.get("settings", {}),
        "choiceLists": [{"id": f"cl_{k}", "choices": v} for k, v in v0.get("choiceLists", {}).items()],
        "variables": variables + computed,
        "blocks": blocks,
        "quotas": quotas,
        "flow": flow,
    }
    if survey["version"] is None:
        del survey["version"]
    return survey, {"nodes": nodes_map}


def build_fixture(folder: Path) -> tuple[str, bool]:
    raw = json.loads((folder / "survey.json").read_text())
    meta: dict[str, Any] = {"fixture": folder.name, "sourceFormat": raw.get("format")}
    try:
        if raw.get("format") == "osp-fixture-survey/0":
            survey, idmap = convert_v0(raw)
        else:
            survey, idmap = raw, {"nodes": {}}
        meta["idmap"] = idmap
        plan, diags = compile_survey(survey)
        meta["diagnostics"] = [d.model_dump(mode="json") for d in diags]
        if plan is None:
            errors = [f"{d.code} {d.pointer}: {d.message}" for d in diags if d.severity == "error"]
            raise ConvertError("osp-spec: " + " | ".join(errors))
        out: dict[str, Any] = plan
    except (ConvertError, KeyError, TypeError) as e:
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


def main() -> int:
    (OUT / "fixtures").mkdir(parents=True, exist_ok=True)
    built = [build_fixture(f) for f in sorted(FIXTURES.iterdir()) if (f / "survey.json").is_file()]
    (OUT / "parity.json").write_text(json.dumps(parity_vectors()))
    ok = sum(1 for _, good in built if good)
    print(f"engine fixtures: {ok}/{len(built)} plans built in {OUT.relative_to(ROOT)}")
    for name, good in built:
        if not good:
            print(f"  not built: {name} (see .build/fixtures/{name}.plan.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
