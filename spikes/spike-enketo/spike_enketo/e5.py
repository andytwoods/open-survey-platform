"""E5 / P8: 1,000 seeds through Enketo's own randomize() (openrosa-xpath-evaluator in headless
Chromium) vs our spec-only Python reimplementation."""

from __future__ import annotations

import json
import random
from pathlib import Path

from playwright.sync_api import sync_playwright

from .xforms_random import randomize

ROOT = Path(__file__).resolve().parent.parent
LENGTHS = [3, 5, 10, 26]

JS = """
([seeds, lengths]) => {
  const out = [];
  for (const n of lengths) {
    const xml = '<root>' + Array.from({length: n}, (_, i) => `<item>${i}</item>`).join('') + '</root>';
    const doc = new DOMParser().parseFromString(xml, 'text/xml');
    for (const s of seeds) {
      const lit = s.kind === 'string' ? `'${s.value}'` : String(s.value);
      try {
        const r = window.ORXE.evaluate(`randomize(/root/item, ${lit})`, doc, null, XPathResult.UNORDERED_NODE_SNAPSHOT_TYPE, null);
        const order = [];
        for (let i = 0; i < r.snapshotLength; i++) order.push(Number(r.snapshotItem(i).textContent));
        out.push({kind: s.kind, seed: s.value, n, order});
      } catch (e) {
        out.push({kind: s.kind, seed: s.value, n, order: null, error: String(e.message || e)});
      }
    }
  }
  return out;
}
"""


def seed_set() -> list[dict]:
    rng = random.Random(20261016)  # fixed: the seed list itself is reproducible
    seeds: list[dict] = []
    seeds += [{"kind": "small", "value": i} for i in range(0, 100)]
    seeds += [{"kind": "random31", "value": rng.randrange(1, 2**31 - 1)} for _ in range(600)]
    seeds += [{"kind": "large", "value": rng.randrange(2**31, 2**53)} for _ in range(100)]
    seeds += [{"kind": "negative", "value": -rng.randrange(1, 2**31)} for _ in range(100)]
    seeds += [{"kind": "decimal", "value": round(rng.uniform(1, 1e6), 3)} for _ in range(50)]
    seeds += [{"kind": "string", "value": f"sess-{rng.randrange(10**9):09d}"} for _ in range(50)]
    assert len(seeds) == 1000
    return seeds


def compare(enketo: list[dict], remainder: str) -> dict:
    by_kind: dict[str, list[int]] = {}
    errors: dict[str, dict] = {}
    mismatches = []
    per_seed: dict[tuple, bool] = {}
    for row in enketo:
        key = (row["kind"], str(row["seed"]))
        if row.get("error"):
            e = errors.setdefault(row["kind"], {"count": 0, "example": row["error"]})
            e["count"] += 1
            ok = False
        else:
            mine = randomize(list(range(row["n"])), row["seed"], remainder)
            ok = mine == row["order"]
            if not ok:
                mismatches.append({**row, "python": mine})
        by_kind.setdefault(row["kind"], [0, 0])
        by_kind[row["kind"]][0] += ok
        by_kind[row["kind"]][1] += 1
        per_seed[key] = per_seed.get(key, True) and ok
    return {
        "comparisons": len(enketo),
        "exact_matches": sum(v[0] for v in by_kind.values()),
        "seeds_matching_all_lengths": sum(per_seed.values()),
        "by_kind": {k: {"match": v[0], "of": v[1]} for k, v in by_kind.items()},
        "enketo_errors_by_kind": errors,
        "mismatches_excluding_errors": len(mismatches),
        "first_mismatches": mismatches[:5],
    }


def run(out_dir: Path) -> dict:
    seeds = seed_set()
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto("about:blank")
        page.add_script_tag(path=str(ROOT / "web/dist/xpath.js"))
        enketo = page.evaluate(JS, [seeds, LENGTHS])
        b.close()
    summary = {
        "seeds": len(seeds),
        "lengths": LENGTHS,
        "note": "comparisons = seeds x lengths; kinds: small 0-99, random31 1..2^31-2, large 2^31..2^53, negative, decimal, string",
        "first_attempt_spec_only_floor_mod": compare(enketo, "floor"),
        "final_trunc_remainder": compare(enketo, "trunc"),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "e5_randomize.json").write_text(json.dumps(summary, indent=1))
    (out_dir / "e5_randomize_all.json").write_text(json.dumps(enketo))
    return summary


def report(s: dict) -> str:
    lines = []
    for k in ("first_attempt_spec_only_floor_mod", "final_trunc_remainder"):
        v = s[k]
        kinds = {kk: f"{x['match']}/{x['of']}" for kk, x in v["by_kind"].items()}
        lines.append(f"E5 {k}: {v['exact_matches']}/{v['comparisons']} orders; seeds exact at all lengths "
                     f"{v['seeds_matching_all_lengths']}/{s['seeds']}; {kinds}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(run(ROOT / "evidence")))
