"""One command: `uv run python -m spike1` (or `make run`). Fresh containers -> deploy via API -> P1..P7 -> export -> checks."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import setup as S
from .checks import run_checks
from .participant import Participant
from .rpc import RC2, unb64
from .scripts import SCRIPTS

HERE = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "evidence" / "run"), help="evidence directory (wiped)")
    ap.add_argument("--keep-up", action="store_true", help="leave containers running afterwards")
    ap.add_argument("--only", nargs="*", help="subset of participants, e.g. P2 P5")
    args = ap.parse_args()
    ev = Path(args.out)
    shutil.rmtree(ev, ignore_errors=True)
    ev.mkdir(parents=True)
    T: dict[str, float] = {}
    t0 = time.perf_counter()

    def mark(name: str) -> None:
        T[name] = round(time.perf_counter() - t0, 2)
        print(f"[{T[name]:7.2f}s] {name}", flush=True)

    S.fresh_containers(); mark("containers_started")
    S.wait_installed(); mark("limesurvey_installed")
    S.enable_rpc()
    c = RC2(); c.login(); mark("rpc_session_key")
    version = {k: c.call("get_site_settings", k) for k in ("versionnumber", "versiondate", "buildnumber", "dbversionnumber")
               if _ok(c, "get_site_settings", k)}
    names = args.only or list(SCRIPTS)
    tokens = {n: f"tok{n.lower()}" for n in names}
    dep = S.deploy(c, list(tokens.values())); mark("survey_imported_activated")
    sid = dep["sid"]
    codes, sgqa, fmap = S.lookup(c, sid)
    _dump(ev / "deploy.json", {"version": version, **dep, "codes": codes, "sgqa": sgqa})
    _dump(ev / "fieldmap.json", fmap)
    inv = {v: k for k, v in sgqa.items()}

    def db(token: str) -> list[dict]:
        r = S.compose("exec", "-T", "db", "mariadb", "-ulimesurvey", "-pspike1-local-db-pw", "limesurvey", "-B",
                      "-e", f"SELECT * FROM lime_survey_{sid} WHERE token='{token}'")
        lines = r.stdout.rstrip("\n").split("\n")
        if len(lines) < 2:
            return []
        head = [inv.get(h, h) for h in lines[0].split("\t")]
        return [dict(zip(head, [None if v == "NULL" else v for v in ln.split("\t")])) for ln in lines[1:]]

    def session_probe(token: str) -> dict:
        """Where does LimeSurvey keep the realised question order? Look inside the PHP session (not the DB)."""
        r = S.compose("exec", "-T", "limesurvey", "sh", "-c", f"grep -l '{token}' /tmp/sess_* | head -1 | xargs cat",
                      check=False)
        raw = r.stdout
        att = {c_: sgqa[c_] for c_ in ("att1", "att2", "att3")}
        keys = [(m.start(1), m.group(1)) for m in re.finditer(r'(?:^|[;}])([A-Za-z][A-Za-z0-9_\-]*)\|', raw)]
        regions = {}
        for i, (pos, k) in enumerate(keys):
            end = keys[i + 1][0] if i + 1 < len(keys) else len(raw)
            seg = raw[pos:end]
            occ = sorted((seg.find(f'"{v}"'), c_) for c_, v in att.items() if seg.find(f'"{v}"') >= 0)
            if occ:
                regions[k] = [c_ for _, c_ in occ]
        seed_hits = re.findall(r'"seed";[a-z]:\d*:?"?(\d+)', raw)
        return {"session_bytes": len(raw), "top_level_keys": [k for _, k in keys][:40],
                "att_order_by_first_occurrence_per_key": regions, "seed_values_in_session": sorted(set(seed_hits))}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for n in names:
            P = Participant(n, browser, sid, tokens[n], codes, sgqa, ev)
            fn = SCRIPTS[n]
            try:
                fn(P, db, session_probe) if n == "P6" else fn(P, db)
            except Exception as e:  # keep going: a failed script is a finding, not a crash
                P.note({"script_error": f"{type(e).__name__}: {e}"})
                try:
                    P.snap("error")
                except Exception:
                    pass
            P.save()
            mark(f"participant_{n}")
        browser.close()
    mark("participants_done")

    exports = {}
    for fmt, head, resp in [("json", "code", "short"), ("json", "code", "long"), ("csv", "code", "short"),
                            ("json", "full", "short")]:
        raw = unb64(c.call("export_responses", sid, fmt, "en", "all", head, resp))
        p = ev / "exports" / f"responses_{head}_{resp}.{fmt}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        exports[(fmt, head, resp)] = raw
    _dump(ev / "exports" / "participants.json",
          c.call("list_participants", sid, 0, 100, False, ["completed", "usesleft"]))
    _dump(ev / "exports" / "survey_summary.json", c.call("get_summary", sid, "all"))
    mark("exported")
    _dump(ev / "rpc_calls.json", c.log)
    c.close()

    results = run_checks(ev, json.loads(exports[("json", "code", "short")]))
    mark("checks_done")
    _dump(ev / "timings.json", T)
    failed = [r for r in results if r["status"] == "FAIL"]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; evidence in {ev}")
    for r in results:
        print(f"  {r['status']:4} {r['id']}: {r['what']}  -> {r['observed']}")
    if not args.keep_up:
        S.compose("down", "-v")
        print("containers stopped (docker compose down -v)")
    return 0


def _ok(c: RC2, m: str, *a) -> bool:
    try:
        c.call(m, *a)
        return True
    except Exception:
        return False


def _dump(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
