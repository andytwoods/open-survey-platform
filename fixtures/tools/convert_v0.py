"""One-off converter (C3b): `osp-fixture-survey/0` -> `osp-survey/0.1`.

Kept as documentation of how the v0 fixtures (written by C3a before `osp-spec` existed) map
onto the real model. It ran once over every `fixtures/*/survey.json`; the v0 originals are in
git history (commit 85db6ad and earlier). Running it again on a converted survey is a no-op.

    uv run python fixtures/tools/convert_v0.py            # convert every fixture in place
    uv run python fixtures/tools/convert_v0.py --check    # convert in memory, write nothing

Mapping (see fixtures/FORMAT.md):

- `title`, `description`, `languages`, `metadata.license`/`ddi` -> `metadata`.
- `choiceLists: {name: [choices]}` -> `[{id, choices}]`; a question's `choices: "name"` ->
  `choiceList: "name"`.
- Every v0 block is one page, so it becomes a `Block` with exactly one `Page`. The block keeps
  the v0 id (traces name blocks: `page`, `expectPage`, `orders.blocks`, `orders.items`); the
  page is `<block>_page`.
- Conditions (`showIf`, `constraint`, branch `if`) are parsed with `osp_expr` into C1's AST.
  The model has no comment field, so the source text is dropped (`osp_expr.to_text` gives it
  back).
- `design.factors` -> `assigned` variables; `{"assign": "design"}` -> an `assign` node listing
  every factor.
- `embeddedData` -> `embedded` variables.
- Flow nodes get the ids the model requires: `n_<block>` for block nodes, `branch_<n>`,
  `end_<code>`, `assign_design`; a randomiser keeps its v0 id.
- Ids must be unique across the whole survey. Where a v0 choice list or block shared an id
  with a question, it gets a `_list` / `_blk` suffix (fixtures 10, 19, 20).

Not expressible in osp-survey/0.1 (fixture 20 only) and therefore left out, listed in the
fixture's `pending.json` and in fixtures/README.md: the `calculate` item (`if()` is not in
the expression grammar), the quota and its `quotaCheck` node (its `when` uses the calculate,
and `onFull` has no outcome), `scores` and `reverseScored`, and `design.allocation`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from osp_expr import EXPR_ADAPTER, parse, to_text

FIXTURES = Path(__file__).resolve().parents[1]
V0 = "osp-fixture-survey/0"
SPEC = "osp-survey/0.1"


# The model requires a label on every question. The review.md §2.3 example (fixture 20)
# left `age` without one; this is the only content the conversion adds.
LABEL_FIXES = {("20-worked-example", "age"): "How old are you?"}


class ConvertError(Exception):
    pass


def expr(src: str, where: str) -> Any:
    result = parse(src)
    if result.expr is None:
        msgs = "; ".join(d.message for d in result.diagnostics)
        raise ConvertError(f"{where}: cannot parse {src!r}: {msgs}")
    again = parse(to_text(result.expr)).expr
    if again != result.expr:
        raise ConvertError(f"{where}: {src!r} does not round-trip through to_text")
    return EXPR_ADAPTER.dump_python(result.expr, mode="json")


class Converter:
    def __init__(self, v0: dict[str, Any], name: str) -> None:
        self.v0 = v0
        self.name = name
        self.used: set[str] = set()
        self.dropped: list[str] = []
        self.branches = 0
        self.question_ids = [item["id"] for blk in v0["blocks"].values() for item in blk["items"]]
        self.used.update(self.question_ids)
        self.list_ids = {cl: self.claim(cl, "_list") for cl in v0.get("choiceLists", {})}
        self.block_ids = {b: self.claim(b, "_blk") for b in v0["blocks"]}

    def claim(self, wanted: str, suffix: str) -> str:
        id_ = wanted
        while id_ in self.used:
            id_ += suffix
        self.used.add(id_)
        return id_

    # -- survey -------------------------------------------------------------------------

    def survey(self) -> dict[str, Any]:
        v0 = self.v0
        metadata: dict[str, Any] = {"title": v0["title"]}
        if "description" in v0:
            metadata["description"] = v0["description"]
        metadata["languages"] = v0["languages"]
        metadata.update(v0.get("metadata", {}))

        out: dict[str, Any] = {
            "specVersion": SPEC,
            "id": v0["id"],
            "version": v0["version"],
            "metadata": metadata,
            "settings": v0.get("settings", {}),
            "choiceLists": [
                {"id": self.list_ids[cl], "choices": choices}
                for cl, choices in v0.get("choiceLists", {}).items()
            ],
        }
        variables = self.variables()
        if variables:
            out["variables"] = variables
        out["blocks"] = [self.block(bid, blk) for bid, blk in v0["blocks"].items()]
        out["flow"] = self.flow(v0["flow"], "flow")
        for key in ("scores", "quotas"):
            if key in v0:
                self.dropped.append(key)
        return out

    def variables(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in self.v0.get("embeddedData", []):
            if e.get("from") != "url":
                raise ConvertError(f"{self.name}: embeddedData from {e.get('from')!r}")
            var: dict[str, Any] = {
                "kind": "embedded",
                "id": self.claim(e["name"], "_var"),
                "param": e["param"],
            }
            if "default" in e:
                var["default"] = e["default"]
            out.append(var)
        design = self.v0.get("design", {})
        for f in design.get("factors", []):
            out.append(
                {"kind": "assigned", "id": self.claim(f["id"], "_var"), "levels": f["levels"]}
            )
        if "allocation" in design:
            self.dropped.append("design.allocation")
        return out

    # -- blocks and items ---------------------------------------------------------------

    def block(self, v0_id: str, blk: dict[str, Any]) -> dict[str, Any]:
        bid = self.block_ids[v0_id]
        page: dict[str, Any] = {"id": self.claim(f"{bid}_page", "_")}
        items = [self.item(i) for i in blk["items"]]
        page["items"] = [i for i in items if i is not None]
        if blk.get("itemOrder", "fixed") != "fixed":
            page["itemOrder"] = blk["itemOrder"]
        return {"id": bid, "pages": [page]}

    def item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        where = f"{self.name}: item {item['id']}"
        if item["type"] == "calculate":
            self.dropped.append(f"calculate {item['id']}")
            return None
        out: dict[str, Any] = {"type": item["type"], "id": item["id"]}
        for key, value in item.items():
            if key in ("id", "type"):
                continue
            if key in ("showIf", "constraint"):
                out[key] = expr(value, f"{where} {key}")
            elif key == "choices":
                out["choiceList"] = self.list_ids[value]
            elif key in ("label", "required", "constraintMessage", "choiceOrder"):
                out[key] = value
            elif key == "reverseScored":
                self.dropped.append(f"reverseScored on {item['id']}")
            else:
                raise ConvertError(f"{where}: unknown field {key!r}")
        if "label" not in out:
            fix = LABEL_FIXES.get((self.name, item["id"]))
            if fix is None:
                raise ConvertError(f"{where}: no label")
            out = {"type": out.pop("type"), "id": out.pop("id"), "label": fix, **out}
        return out

    # -- flow ---------------------------------------------------------------------------

    def flow(self, nodes: list[dict[str, Any]], where: str) -> list[dict[str, Any]]:
        out = []
        for node in nodes:
            converted = self.node(node, where)
            if converted is not None:
                out.append(converted)
        return out

    def node(self, node: dict[str, Any], where: str) -> dict[str, Any] | None:
        (kind, body), *rest = node.items()
        if rest:
            raise ConvertError(f"{self.name}: {where}: flow node with several keys {node}")
        if kind == "block":
            bid = self.block_ids[body]
            return {"type": "block", "id": self.claim(f"n_{bid}", "_"), "block": bid}
        if kind == "branch":
            self.branches += 1
            out: dict[str, Any] = {
                "type": "branch",
                "id": self.claim(f"branch_{self.branches}", "_"),
                "if": expr(body["if"], f"{self.name}: {where} branch if"),
                "then": self.flow(body["then"], where),
            }
            if body.get("else"):
                out["else"] = self.flow(body["else"], where)
            return out
        if kind == "randomiser":
            return {
                "type": "randomiser",
                "id": self.claim(body["id"], "_"),
                "children": self.flow(body["shuffle"], where),
            }
        if kind == "assign":
            if body != "design":
                raise ConvertError(f"{self.name}: assign {body!r}")
            return {
                "type": "assign",
                "id": self.claim("assign_design", "_"),
                "variables": [f["id"] for f in self.v0["design"]["factors"]],
            }
        if kind == "end":
            out = {"type": "end", "id": self.claim(f"end_{body}", "_")}
            if body != "complete":
                out["outcome"] = body
            return out
        if kind == "quotaCheck":
            self.dropped.append(f"quotaCheck {body}")
            return None
        raise ConvertError(f"{self.name}: {where}: unknown flow node {kind!r}")


def convert(path: Path, *, write: bool) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("specVersion") == SPEC:
        return ["already converted"]
    if data.get("format") != V0:
        raise ConvertError(f"{path}: not {V0}")
    conv = Converter(data, path.parent.name)
    out = conv.survey()
    if write:
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return conv.dropped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="convert in memory, write nothing")
    args = ap.parse_args()
    for path in sorted(FIXTURES.glob("[0-9][0-9]-*/survey.json")):
        dropped = convert(path, write=not args.check)
        print(f"{path.parent.name}: {', '.join(dropped) or 'ok'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
