"""Scripted participants P1-P7 (+P5b, P9) against our server + Enketo, and the E10 axe scan.

Each script returns {"id", "pages", "checks": [{name, expected, actual, ok}], ...} and is written to
evidence/run/<id>.json. Checks encode semantics.md; a failed check is a finding, not a crash.
"""

from __future__ import annotations

import json
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

from playwright.sync_api import Page

from .server import DATA, SURVEY_VERSION, load_session
from .xforms_random import randomize, substream_seed

ROOT = Path(__file__).resolve().parent.parent
COLOURS = ["red", "green", "blue", "yellow", "purple"]


class Run:
    def __init__(self, pid: str, page: Page, base: str):
        self.id, self.page, self.base = pid, page, base
        self.checks: list[dict] = []
        self.notes: list[str] = []
        self.console: list[str] = []
        page.on("console", lambda m: self.console.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.console.append(f"pageerror: {e}"))

    # ---- navigation helpers -------------------------------------------------
    def start(self, query: str = "") -> None:
        self.page.goto(f"{self.base}/start{('?' + query) if query else ''}")
        self.wait_ready()

    def wait_ready(self) -> None:
        self.page.wait_for_function("document.body.dataset.ready === '1'")

    @property
    def sid(self) -> str:
        return self.page.url.rstrip("/").split("/")[-1]

    def cur(self) -> str | None:
        return self.page.evaluate(
            "() => { const c = window.__form.pages.current; return c && (c.getAttribute('name') || c.querySelector('[name]').getAttribute('name')); }"
        )

    def radio(self, name: str, value: str) -> None:
        self.page.check(f'input[name="/data/{name}"][value="{value}"]')

    def fill(self, name: str, text: str) -> None:
        loc = self.page.locator(f'[name="/data/{name}"]')
        loc.fill(text)
        loc.dispatch_event("change")

    def next(self) -> str | None:
        if self.page.locator(".next-page.disabled").count():
            return self.cur()
        self.page.click(".next-page")
        self.page.wait_for_timeout(300)
        return self.cur()

    def back(self) -> str | None:
        self.page.click(".previous-page")
        self.page.wait_for_timeout(300)
        return self.cur()

    def submit(self) -> None:
        self.page.click("#submit-form")
        self.page.wait_for_selector("#done", timeout=5000)

    def flush_draft(self) -> None:
        self.page.wait_for_timeout(200)
        self.page.evaluate("() => window.__draftPending")

    def model_value(self, local: str) -> str | None:
        return self.page.evaluate(
            "(n) => { const el = window.__form.model.xml.querySelector(n); return el ? el.textContent : null; }", local
        )

    def question_order(self, group: str) -> list[str]:
        return self.page.evaluate(
            """(g) => [...document.querySelectorAll(`section[name="/data/${g}"] > .question`)]
                 .map(q => q.querySelector('[name]').getAttribute('name').split('/').pop())""",
            group,
        )

    def block_order(self) -> list[str]:
        return self.page.evaluate(
            "() => [...document.querySelectorAll('[role=page]')].map(e => e.getAttribute('name').split('/').pop()).filter(n => n.startsWith('blk_'))"
        )

    def choice_order(self, name: str) -> list[str]:
        return self.page.evaluate(
            "(n) => [...document.querySelectorAll(`input[name='/data/${n}']`)].map(i => i.value).filter(v => v)", name
        )

    def label_text(self, name: str) -> str:
        return self.page.evaluate(
            """(n) => { const i = document.querySelector(`[name='/data/${n}']`);
                 const q = i.closest('.question'); const l = q.querySelector('.question-label.active');
                 return l ? l.textContent.replace(/\\s+/g, ' ').trim() : null; }""",
            name,
        )

    # ---- checks -------------------------------------------------------------
    def check(self, name: str, expected, actual) -> bool:
        ok = expected == actual
        self.checks.append({"name": name, "expected": expected, "actual": actual, "ok": ok})
        return ok

    def submission(self) -> dict:
        sub = DATA / "submissions"
        out = {}
        for kind in ("raw", "pruned"):
            p = sub / f"{self.sid}.{kind}.xml"
            out[kind] = p.read_text() if p.exists() else None
        return out

    def result(self) -> dict:
        return {
            "id": self.id,
            "sid": self.sid,
            "pages": self.page.evaluate("() => window.__pageLog || null") if not self.page.is_closed() else None,
            "checks": self.checks,
            "notes": self.notes,
            "console": self.console,
            "pass": all(c["ok"] for c in self.checks),
        }


def leaves(xml: str | None) -> dict[str, str | None]:
    """Map leaf local-name -> text ('' for empty) for every leaf present in the instance."""
    if xml is None:
        return {}
    root = ET.fromstring(xml)
    out = {}
    for el in root.iter():
        if len(el) == 0:
            out[el.tag.split("}")[-1]] = el.text or ""
    return out


def exp_orders(seed: int) -> dict:
    return {
        "order_att": randomize(["att1", "att2", "att3"], substream_seed(SURVEY_VERSION, seed, "p_att")),
        "order_blocks": randomize(["blk_x", "blk_y"], substream_seed(SURVEY_VERSION, seed, "blocks")),
        "colour": randomize(COLOURS, seed),
    }


# ---- scripts ---------------------------------------------------------------------------


def p1(r: Run) -> None:
    """Consent no -> ends immediately; no other answers stored."""
    r.start()
    r.radio("p_consent/consent", "no")
    r.page.wait_for_timeout(200)
    r.check("Next hidden after 'no' (only page left)", True, r.page.locator(".next-page").is_hidden())
    r.submit()
    sub = r.submission()
    pr, raw = leaves(sub["pruned"]), leaves(sub["raw"])
    r.check("pruned: consent == no", "no", pr.get("consent"))
    r.check("pruned: no age/att/followup/colour nodes", [], [k for k in ("age", "att1", "followup", "fav_colour", "q_x") if k in pr])
    r.check("raw: later answers empty", True, all(raw.get(k, "") == "" for k in ("age", "att1", "followup", "fav_colour")))
    r.check("pages seen", ["/data/p_consent"], json.loads((DATA / "submissions" / f"{r.sid}.pages.json").read_text()))


def _consent_age(r: Run, age: str = "30") -> str | None:
    r.radio("p_consent/consent", "yes")
    r.check("consent -> p_age", "/data/p_age", r.next())
    r.fill("p_age/age", age)
    return r.next()


def p2(r: Run) -> None:
    """Server-assigned condition, straight through, att1=5: follow-up shown + required; orders recorded."""
    r.start()
    s = load_session(r.sid)
    cond, seed = s["cond"], s["seed"]
    exp = exp_orders(seed)
    r.radio("p_consent/consent", "yes")
    r.next()
    # required: empty age blocks
    r.check("required: empty age blocks Next", "/data/p_age", r.next())
    r.fill("p_age/age", "12")
    r.check("constraint: age 12 blocks Next", "/data/p_age", r.next())
    r.fill("p_age/age", "30")
    r.check(f"cond {cond}: stimulus page", f"/data/p_stim_{cond.lower()}", r.next())
    r.check("model cond == session cond", cond, r.model_value("cond"))
    r.check("att page reached", "/data/p_att", r.next())
    r.check("E6: att question DOM order == server order (Python)", exp["order_att"], r.question_order("p_att"))
    r.check("E9 piping: att1 label shows cond", True, f"condition {cond} story" in (r.label_text("p_att/att1") or ""))
    r.radio("p_att/att1", "5")
    r.radio("p_att/att2", "3")
    r.radio("p_att/att3", "4")
    r.check("att1>=4 -> follow-up page", "/data/p_follow", r.next())
    flabel = r.label_text("p_follow/followup")
    r.check("E9 piping: ${att1} in label (semantics: label 'Strongly agree')", "FOLLOWUP: You chose Strongly agree", (flabel or "").split(" (")[0])
    r.check("E9 piping lowered: jr:choice-name label in calculate", True, "(Strongly agree)" in (flabel or ""))
    r.notes.append(f"follow-up label rendered: {flabel!r}")
    # required: empty blocks
    r.check("required: empty follow-up blocks Next", "/data/p_follow", r.next())
    # whitespace-only: semantics says answered
    r.fill("p_follow/followup", "   ")
    after_ws = r.next()
    r.check("semantics §2: whitespace-only counts as answered (advances)", "/data/p_colour", after_ws)
    if after_ws != "/data/p_follow":
        r.back()
    r.fill("p_follow/followup", "  loved it  ")
    r.check("follow-up -> colour", "/data/p_colour", r.next())
    r.check("E5 in-form: colour choice order == Python randomize(seed)", exp["colour"], r.choice_order("p_colour/fav_colour"))
    r.radio("p_colour/fav_colour", "red")
    first_blk = r.next()
    r.check("E6: block order == server order", exp["order_blocks"], r.block_order())
    r.check("first block page is order_blocks[0]", f"/data/{exp['order_blocks'][0]}", first_blk)
    for _ in range(2):
        if r.cur() == "/data/blk_x":
            r.fill("blk_x/q_x", "7")
        r.next()
    r.submit()
    sub = leaves(r.submission()["pruned"])
    r.check("sub: cond", cond, sub.get("cond"))
    r.check("sub: seed", str(seed), sub.get("seed"))
    r.check("sub: order_att recorded", " ".join(exp["order_att"]), sub.get("order_att"))
    r.check("sub: order_blocks recorded", " ".join(exp["order_blocks"]), sub.get("order_blocks"))
    raw = leaves(r.submission()["raw"])
    r.check("sub raw getDataStr(): text stored exactly (no trim)", "  loved it  ", raw.get("followup"))
    r.check("sub pruned getDataStr({irrelevant:false}): text stored exactly (no trim)", "  loved it  ", sub.get("followup"))
    r.check("sub: att1_label", "Strongly agree", sub.get("att1_label"))
    r.check("sub: q_y unanswered present but empty", "", sub.get("q_y"))
    r.check("sub: instanceID", True, (sub.get("instanceID") or "").startswith("uuid:"))


def p3(r: Run) -> None:
    """att1 = 2: follow-up not shown, not required."""
    r.start()
    _consent_age(r)
    r.next()  # stimulus -> att
    for q, v in (("att1", "2"), ("att2", "2"), ("att3", "2")):
        r.radio(f"p_att/{q}", v)
    r.check("att1=2 skips follow-up", "/data/p_colour", r.next())
    r.next()
    r.next()
    r.submit()
    sub = r.submission()
    r.check("pruned: no followup node", False, "followup" in leaves(sub["pruned"]))
    r.check("raw: followup empty", "", leaves(sub["raw"]).get("followup"))


def p4(r: Run, extra: str = "") -> None:
    """Server injects cond=B, seed=123 (E4)."""
    r.start("cond=B&seed=123" + extra)
    exp = exp_orders(123)
    r.check("model cond injected", "B", r.model_value("cond"))
    r.check("model seed injected", "123", r.model_value("seed"))
    r.check("cond B -> stimulus B", "/data/p_stim_b", _consent_age(r))
    r.check("stimulus B text visible", True, r.page.locator("text=STIMULUS-B").first.is_visible())
    r.next()
    r.check("E6 att order (seed 123)", exp["order_att"], r.question_order("p_att"))
    for q in ("att1", "att2", "att3"):
        r.radio(f"p_att/{q}", "3")
    r.next()
    r.check("E5 in-form colour order (seed 123)", exp["colour"], r.choice_order("p_colour/fav_colour"))
    r.notes.append(f"seed 123 colour order: {r.choice_order('p_colour/fav_colour')}")
    r.next()
    r.next()
    r.submit()
    sub = leaves(r.submission()["pruned"])
    r.check("sub cond/seed", ("B", "123"), (sub.get("cond"), sub.get("seed")))


def p4s(r: Run) -> None:
    """P4 on the slim widget bundle (E1 size experiment)."""
    p4(r, "&slim=1")
    r.check("slim bundle served", "/static/app-slim.js", r.page.evaluate("() => document.querySelector('script[src]').getAttribute('src')"))


def _p5(r: Run, query: str) -> None:
    r.start(query)
    _consent_age(r)
    r.next()
    r.radio("p_att/att1", "5")
    r.radio("p_att/att2", "4")
    r.radio("p_att/att3", "4")
    r.next()
    r.fill("p_follow/followup", "temporary answer")
    r.check("follow-up -> colour", "/data/p_colour", r.next())
    r.check("back -> follow-up", "/data/p_follow", r.back())
    r.check("back -> att", "/data/p_att", r.back())
    r.radio("p_att/att1", "2")
    r.page.wait_for_timeout(200)
    r.notes.append(f"model followup after irrelevance (before submit): {r.model_value('followup')!r}")
    r.check("forward skips follow-up", "/data/p_colour", r.next())
    # relevance returns after the page was submitted: semantics §3 says the value was cleared
    r.check("back -> att (2nd time)", "/data/p_att", r.back())
    r.radio("p_att/att1", "5")
    r.check("att1=5 again -> follow-up", "/data/p_follow", r.next())
    shown = r.page.locator('[name="/data/p_follow/followup"]').input_value()
    r.notes.append(f"follow-up value shown when relevance returned: {shown!r}")
    r.check("semantics §3: value gone when relevance returns after page submit", "", shown)
    r.back()
    r.radio("p_att/att1", "2")
    r.next()
    r.next()
    r.next()
    r.submit()
    sub = r.submission()
    raw, pr = leaves(sub["raw"]), leaves(sub["pruned"])
    r.notes.append(f"raw getDataStr() followup={raw.get('followup')!r}; pruned getDataStr({{irrelevant:false}}) has node={'followup' in pr}")
    r.check("E8 raw (after form.validate()): followup cleared", "", raw.get("followup"))
    r.check("E8 pruned: followup node absent", False, "followup" in pr)


def p5(r: Run) -> None:
    """att1=5, answer follow-up, back, att1->2, submit (default config)."""
    _p5(r, "")


def p5b(r: Run) -> None:
    """P5 with config.excludeNonRelevant = true."""
    _p5(r, "xnr=1")


def p5c(r: Run) -> None:
    """P5 with our lowering: form.clearNonRelevant() on every page flip (semantics §3)."""
    _p5(r, "cnr=1")


def p6(r: Run) -> None:
    """Refresh mid-page and resume: same page, values, order, condition (E7)."""
    r.start()
    s = load_session(r.sid)
    exp = exp_orders(s["seed"])
    _consent_age(r, "41")
    r.next()
    r.radio("p_att/att1", "4")
    before = {"page": r.cur(), "order": r.question_order("p_att"), "cond": r.model_value("cond")}
    r.flush_draft()
    r.page.reload()
    r.wait_ready()
    after = {"page": r.cur(), "order": r.question_order("p_att"), "cond": r.model_value("cond")}
    r.check("resume: same page", before["page"], after["page"])
    r.check("resume: same question order", before["order"], after["order"])
    r.check("resume: same cond", before["cond"], after["cond"])
    r.check("resume: att1 still 4", True, r.page.is_checked('input[name="/data/p_att/att1"][value="4"]'))
    r.check("resume: age kept", "41", r.model_value("age"))
    r.check("back after resume -> own stimulus", f"/data/p_stim_{s['cond'].lower()}", r.back())
    r.next()
    r.radio("p_att/att2", "1")
    r.radio("p_att/att3", "1")
    r.next()
    r.fill("p_follow/followup", "  x  ")
    r.next()
    r.flush_draft()
    r.page.reload()
    r.wait_ready()
    r.check("resume on colour page", "/data/p_colour", r.cur())
    r.check("colour order after reload == Python", exp["colour"], r.choice_order("p_colour/fav_colour"))
    r.check("resume keeps text exactly (semantics §2)", "  x  ", r.model_value("followup"))
    r.next()
    r.next()
    r.submit()
    sub = leaves(r.submission()["pruned"])
    r.check("sub: answers from before reload kept", ("41", "4"), (sub.get("age"), sub.get("att1")))


def p7(r: Run, sid: str) -> None:
    """Re-enter the survey link after finishing (uses P2's session)."""
    before = load_session(sid)
    r.page.goto(f"{r.base}/s/{sid}")
    r.check("re-entry shows already-completed", True, r.page.locator("#already").is_visible())
    resp = r.page.request.post(f"{r.base}/s/{sid}/submit", data=json.dumps({"raw": "<x/>", "pruned": "<x/>"}),
                               headers={"Content-Type": "application/json"})
    r.check("second submit rejected", 409, resp.status)
    after = load_session(sid)
    r.check("no reallocation (cond/seed unchanged)", (before["cond"], before["seed"]), (after["cond"], after["seed"]))


def p9_keyboard(r: Run) -> None:
    """E10: complete the survey with the keyboard only."""
    pg = r.page
    r.start("cond=A&seed=7")

    def tab_to(selector: str, limit: int = 60) -> bool:
        for _ in range(limit):
            pg.keyboard.press("Tab")
            if pg.evaluate("(s) => !!document.activeElement && document.activeElement.matches(s)", selector):
                return True
        return False

    def kb_radio(name: str, value: str) -> bool:
        if not tab_to(f'input[name="/data/{name}"]'):
            return False
        for _ in range(10):
            if pg.evaluate("() => document.activeElement.value") == value:
                pg.keyboard.press("Space")
                return pg.is_checked(f'input[name="/data/{name}"][value="{value}"]')
            pg.keyboard.press("ArrowDown")
        return False

    def kb_next() -> str | None:
        ok = tab_to(".next-page")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(300)
        return r.cur() if ok else None

    r.check("kb: consent", True, kb_radio("p_consent/consent", "yes"))
    r.check("kb: -> age", "/data/p_age", kb_next())
    r.check("kb: focus age", True, tab_to('input[name="/data/p_age/age"]'))
    pg.keyboard.type("25")
    r.check("kb: -> stim A", "/data/p_stim_a", kb_next())
    r.check("kb: -> att", "/data/p_att", kb_next())
    for q, v in (("att1", "2"), ("att2", "3"), ("att3", "1")):
        r.check(f"kb: {q}={v}", True, kb_radio(f"p_att/{q}", v))
    r.check("kb: -> colour", "/data/p_colour", kb_next())
    r.check("kb: colour blue", True, kb_radio("p_colour/fav_colour", "blue"))
    kb_next()
    kb_next()
    r.check("kb: focus submit", True, tab_to("#submit-form"))
    pg.keyboard.press("Enter")
    pg.wait_for_selector("#done", timeout=5000)
    sub = leaves(r.submission()["pruned"])
    r.check("kb: submission values", ("yes", "25", "2", "blue"), (sub.get("consent"), sub.get("age"), sub.get("att1"), sub.get("fav_colour")))


def axe_scan(r: Run) -> dict:
    """E10: axe-core on each page of the rendered form."""
    pg = r.page
    r.start("cond=A&seed=99")
    axe_src = (ROOT / "web/node_modules/axe-core/axe.min.js").read_text()
    results = {}

    def scan(label: str):
        if not pg.evaluate("() => !!window.axe"):
            pg.add_script_tag(content=axe_src)
        res = pg.evaluate(
            "async () => { const r = await axe.run(document, {resultTypes: ['violations']}); "
            "return r.violations.map(v => ({id: v.id, impact: v.impact, tags: v.tags.filter(t => t.startsWith('wcag')), help: v.help, "
            "nodes: v.nodes.length, targets: v.nodes.slice(0,3).map(n => n.target.join(' '))})); }"
        )
        results[label] = res

    scan("p_consent")
    r.radio("p_consent/consent", "yes")
    r.next()
    scan("p_age")
    r.fill("p_age/age", "5")
    r.next()
    scan("p_age_with_constraint_error")
    r.fill("p_age/age", "50")
    r.next()
    scan("p_stim_a")
    r.next()
    scan("p_att")
    for q in ("att1", "att2", "att3"):
        r.radio(f"p_att/{q}", "5")
    r.next()
    scan("p_follow")
    r.fill("p_follow/followup", "ok")
    r.next()
    scan("p_colour")
    agg: dict[str, dict] = {}
    for page_res in results.values():
        for v in page_res:
            a = agg.setdefault(v["id"], {"impact": v["impact"], "tags": v["tags"], "help": v["help"], "pages": 0, "nodes": 0, "targets": v["targets"]})
            a["pages"] += 1
            a["nodes"] += v["nodes"]
    r.notes.append(f"axe violations (rule -> pages): { {k: v['pages'] for k, v in agg.items()} }")
    return {"per_page": results, "by_rule": agg}


SCRIPTS = [("P1", p1), ("P2", p2), ("P3", p3), ("P4", p4), ("P4s", p4s), ("P5", p5), ("P5b", p5b), ("P5c", p5c), ("P6", p6), ("P9", p9_keyboard)]


def run_all(browser, base: str, out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    results = []
    p2_sid = None
    for pid, fn in SCRIPTS:
        page = browser.new_page()
        r = Run(pid, page, base)
        try:
            fn(r)
        except Exception as e:  # never crash the run: record as a failed check
            r.check("script completed", "no exception", f"{type(e).__name__}: {e}"[:400])
            r.notes.append(traceback.format_exc()[-1500:])
            page.screenshot(path=str(out / f"{pid}.failure.png"), full_page=True)
        res = r.result()
        res["doc"] = (fn.__doc__ or "").strip()
        if pid == "P2":
            p2_sid = res["sid"]
        results.append(res)
        (out / f"{pid}.json").write_text(json.dumps(res, indent=1))
        page.close()
    page = browser.new_page()
    r = Run("P7", page, base)
    try:
        p7(r, p2_sid)
    except Exception as e:
        r.check("script completed", "no exception", f"{type(e).__name__}: {e}"[:400])
    res = r.result()
    res["doc"] = (p7.__doc__ or "").strip()
    results.append(res)
    (out / "P7.json").write_text(json.dumps(res, indent=1))
    page.close()
    page = browser.new_page()
    r = Run("A11Y", page, base)
    try:
        axe = axe_scan(r)
        (out.parent / "e10_axe.json").write_text(json.dumps(axe, indent=1))
    except Exception as e:
        r.check("axe scan completed", "no exception", f"{type(e).__name__}: {e}"[:400])
    page.close()
    return results
