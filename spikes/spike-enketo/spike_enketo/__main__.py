"""One-command spike run: publish -> serve -> E5 -> participants -> E10 axe -> E11 licences -> summary."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import e5, participants, publish
from .server import DATA, serve

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "evidence"


def licences() -> dict:
    web = ROOT / "web"
    out = {}
    for label, args in (("production", ["--production"]), ("all", [])):
        res = subprocess.run(["npx", "--no-install", "license-checker", "--json", *args], cwd=web, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        data.pop("spike-enketo-web@0.0.0", None)
        counts: dict[str, int] = {}
        for v in data.values():
            lic = v.get("licenses")
            lic = " OR ".join(lic) if isinstance(lic, list) else str(lic)
            counts[lic] = counts.get(lic, 0) + 1
        copyleft = {k: v.get("licenses") for k, v in data.items()
                    if any(t in str(v.get("licenses")).upper() for t in ("GPL", "LGPL", "AGPL", "MPL", "EPL", "CDDL", "EUPL", "CC-BY-SA", "UNKNOWN", "UNLICENSED", "CUSTOM"))}
        out[label] = {"packages": len(data), "by_licence": dict(sorted(counts.items(), key=lambda kv: -kv[1])), "flagged": copyleft}
    summ = subprocess.run(["npx", "--no-install", "license-checker", "--production", "--summary"], cwd=web, capture_output=True, text=True)
    (EV / "e11_license_summary_production.txt").write_text(summ.stdout)
    # Python side
    py = subprocess.run([sys.executable, "-c", "import importlib.metadata as m, json; print(json.dumps({d.metadata['Name']: (d.metadata.get('License-Expression') or d.metadata.get('License') or ';'.join(c for c in (d.metadata.get_all('Classifier') or []) if c.startswith('License'))) for d in m.distributions()}))"],
                        capture_output=True, text=True, check=True)
    out["python"] = json.loads(py.stdout)
    return out


def main() -> int:
    t0 = time.perf_counter()
    if DATA.exists():
        shutil.rmtree(DATA)
    for d in (EV / "run",):
        if d.exists():
            shutil.rmtree(d)
    EV.mkdir(exist_ok=True)
    timings = {}

    t = time.perf_counter()
    pub = publish.main()
    timings["publish_s"] = round(time.perf_counter() - t, 2)
    (EV / "e2_publish.json").write_text(json.dumps({k: pub[k] for k in ("transformerVersion", "transformMs", "browser", "xformSha256")}, indent=1))

    httpd = serve(0)  # ephemeral port: never collides with other servers
    port = httpd.server_address[1]
    try:
        t = time.perf_counter()
        e5sum = e5.run(EV)
        timings["e5_s"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        with sync_playwright() as p:
            b = p.chromium.launch()
            results = participants.run_all(b, f"http://127.0.0.1:{port}", EV / "run")
            b.close()
        timings["participants_s"] = round(time.perf_counter() - t, 2)
    finally:
        httpd.shutdown()
        httpd.server_close()
    shutil.copytree(DATA / "submissions", EV / "run" / "submissions")

    t = time.perf_counter()
    lic = licences()
    (EV / "e11_licences.json").write_text(json.dumps(lic, indent=1))
    timings["licences_s"] = round(time.perf_counter() - t, 2)

    sizes = json.loads((ROOT / "web/dist/sizes.json").read_text())
    timings["total_s"] = round(time.perf_counter() - t0, 2)
    summary = {
        "timings": timings,
        "bundle": sizes,
        "e5": {k: {kk: e5sum[k][kk] for kk in ("exact_matches", "comparisons", "seeds_matching_all_lengths")} for k in ("first_attempt_spec_only_floor_mod", "final_trunc_remainder")},
        "participants": {r["id"]: {"pass": r["pass"], "failed": [c["name"] for c in r["checks"] if not c["ok"]]} for r in results},
        "licences": {k: {"packages": v["packages"], "flagged": v["flagged"]} for k, v in lic.items() if k != "python"},
    }
    (EV / "summary.json").write_text(json.dumps(summary, indent=1))
    print(e5.report(e5sum))
    for r in results:
        bad = [c for c in r["checks"] if not c["ok"]]
        print(f"{r['id']:5} {'PASS' if r['pass'] else 'FAIL'} {len(r['checks']) - len(bad)}/{len(r['checks'])}" + "".join(f"\n      x {c['name']}: expected {c['expected']!r} got {c['actual']!r}" for c in bad))
    print("licences flagged:", {k: v["flagged"] for k, v in summary["licences"].items()})
    print("timings:", timings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
