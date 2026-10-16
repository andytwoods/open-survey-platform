"""Scripted LimeSurvey participant (Playwright). Records every page it sees to a JSON trace."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page

from .rpc import BASE

MARKERS = re.compile(r"(STIMULUS-[AB]|END-OF-SURVEY|PIPE[A-Z]*\[[^\]]*\])")


class Participant:
    def __init__(self, name: str, browser: Browser, sid: int, token: str, codes: dict[int, str],
                 sgqa: dict[str, str], evidence: Path) -> None:
        self.name, self.browser, self.sid, self.token = name, browser, sid, token
        self.codes, self.sgqa, self.evidence = codes, sgqa, evidence
        self.trace: list[dict[str, Any]] = []
        self.notes: list[Any] = []
        self.ctx = browser.new_context()
        self.page: Page = self.ctx.new_page()
        self._shot = 0

    # ---------- navigation ----------
    def url(self, **extra: str) -> str:
        q = "&".join(f"{k}={v}" for k, v in extra.items())
        return f"{BASE}/index.php?r=survey/index&sid={self.sid}&token={self.token}&lang=en" + (f"&{q}" if q else "")

    def open(self, label: str = "open", **extra: str) -> dict[str, Any]:
        self.page.goto(self.url(**extra))
        self.page.wait_for_load_state("networkidle")
        return self.snap(label)

    def new_session(self) -> None:
        """Throw away cookies (a different browser / device), keep the token."""
        self.ctx.close()
        self.ctx = self.browser.new_context()
        self.page = self.ctx.new_page()

    def reload(self, label: str = "reload") -> dict[str, Any]:
        self.page.reload()
        self.page.wait_for_load_state("networkidle")
        return self.snap(label)

    def _click(self, sel: str, label: str) -> dict[str, Any]:
        with self.page.expect_navigation(wait_until="networkidle"):
            self.page.click(sel)
        return self.snap(label)

    def next(self, label: str = "next") -> dict[str, Any]:
        return self._click("#ls-button-submit", label)

    def prev(self, label: str = "prev") -> dict[str, Any]:
        return self._click("#ls-button-previous", label)

    # ---------- answering ----------
    def _choose(self, code: str, value: str) -> None:
        el_id = f"answer{self.sgqa[code]}{value}"
        lab = self.page.locator(f"label[for='{el_id}']")
        if lab.count() and lab.first.is_visible():
            lab.first.click()
        else:
            self.page.check(f"#{el_id}", force=True)

    def yesno(self, code: str, value: str) -> None:
        self._choose(code, value)

    def five(self, code: str, value: int) -> None:
        self._choose(code, str(value))

    def fill(self, code: str, value: str) -> None:
        self.page.fill(f"#answer{self.sgqa[code]}", value)
        self.page.locator(f"#answer{self.sgqa[code]}").dispatch_event("change")

    def value_of(self, code: str) -> str | None:
        """Current value shown in the form for a question (None if not on page)."""
        sg = self.sgqa[code]
        return self.page.evaluate(
            """(sg) => {
                const r = document.querySelector(`input[type=radio][name="${sg}"]:checked`);
                if (r) return r.value;
                const t = document.getElementById('answer' + sg);
                if (t && t.type !== 'radio') return t.value;
                return document.querySelector(`[name="${sg}"]`) ? '' : null;
            }""", sg)

    # ---------- observation ----------
    def snap(self, label: str) -> dict[str, Any]:
        pg = self.page
        info = pg.evaluate(
            """() => {
              const qs = [...document.querySelectorAll('div.question-container[id^=question]')];
              const vis = qs.filter(e => e.offsetParent !== null && !e.classList.contains('ls-hidden'))
                            .map(e => e.id.replace('question',''));
              const hidden = qs.filter(e => !(e.offsetParent !== null && !e.classList.contains('ls-hidden')))
                            .map(e => e.id.replace('question',''));
              const errs = [...document.querySelectorAll(
                    '.has-error, .input-error, .text-danger, .ls-em-error, .alert-danger, #bootstrap-alert-box-modal .modal-body')]
                    .filter(e => e.offsetParent !== null).map(e => e.innerText.trim()).filter(Boolean);
              const step = document.getElementById('thisstep');
              return {visible: vis, hidden_in_dom: hidden, errors: [...new Set(errs)],
                      thisstep: step ? step.value : null,
                      has_prev: !!document.getElementById('ls-button-previous'),
                      has_next: !!document.getElementById('ls-button-submit'),
                      text: document.body.innerText,
                      qtext_html: Object.fromEntries(vis.map(id => {
                          const el = document.querySelector('#question' + id + ' .question-text, #question' + id + ' .ls-label-question');
                          return [id, el ? el.innerHTML.trim().slice(0, 400) : null]; }))};
            }""")
        text = info.pop("text")
        markers = MARKERS.findall(text)
        self._shot += 1
        shot = self.evidence / "screenshots" / f"{self.name}_{self._shot:02d}_{label}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(shot), full_page=True)
        entry = {
            "n": self._shot, "label": label, "t": round(time.time(), 3),
            "questions": [self.codes.get(int(q), q) for q in info["visible"]],
            "questions_hidden_in_dom": [self.codes.get(int(q), q) for q in info["hidden_in_dom"]],
            "markers": markers, "errors": info["errors"], "thisstep": info["thisstep"],
            "has_prev": info["has_prev"], "has_next": info["has_next"],
            "url": pg.url, "screenshot": str(shot.relative_to(self.evidence)),
            "question_html": {self.codes.get(int(k), k): v for k, v in info["qtext_html"].items()},
        }
        if not entry["questions"]:
            main = " ".join(text.split())
            entry["page_text"] = main[:600]
        self.trace.append(entry)
        self._dismiss_modal()
        return entry

    def _dismiss_modal(self) -> None:
        modal = self.page.locator("#bootstrap-alert-box-modal.show")
        if modal.count():
            btn = modal.locator("button[data-bs-dismiss=modal], .btn-close, .modal-footer button")
            if btn.count():
                btn.first.click()
            else:
                self.page.keyboard.press("Escape")
            modal.wait_for(state="hidden", timeout=5000)

    def note(self, msg: Any) -> None:
        self.notes.append(msg)

    def save(self) -> Path:
        out = self.evidence / "traces" / f"{self.name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"participant": self.name, "token": self.token, "pages": self.trace,
                                   "notes": self.notes}, indent=2))
        self.ctx.close()
        return out
