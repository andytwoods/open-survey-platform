"""Minimal participant server (stdlib only).

GET  /start[?cond=A|B&seed=N&xnr=1]  new session -> 303 /s/<sid>. cond/seed query overrides are
                                      TEST-ONLY (P4); normally the server assigns both.
GET  /s/<sid>                         page: published form HTML + model with cond/seed/orders injected,
                                      plus the saved draft (resume) if any. Completed -> "already done".
POST /s/<sid>/draft                   {xml, page} autosave
POST /s/<sid>/submit                  {raw, pruned, pages} -> data/submissions/<sid>.*.xml
GET  /static/*                        web/dist bundle
"""

from __future__ import annotations

import html
import json
import secrets
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.dom import minidom

from .xforms_random import randomize, substream_seed

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web/dist"
DATA = ROOT / "data"
PUBLISHED = ROOT / "build/spike_enketo.json"
SURVEY_VERSION = "2026101601"
ATT_ITEMS = ["att1", "att2", "att3"]
BLOCKS = ["blk_x", "blk_y"]
LOCK = threading.Lock()


def _load_published() -> dict:
    return json.loads(PUBLISHED.read_text())


def new_session(cond: str | None, seed: int | None, xnr: bool, cnr: bool = False) -> dict:
    sid = uuid.uuid4().hex[:12]
    cond = cond if cond in ("A", "B") else secrets.choice(["A", "B"])
    seed = seed if seed is not None else secrets.randbelow(2**31 - 2) + 1
    # Realised orders: computed once, here, with our Python randomize, fixed for the session (E6).
    s = {
        "sid": sid,
        "cond": cond,
        "seed": seed,
        "order_att": randomize(ATT_ITEMS, substream_seed(SURVEY_VERSION, seed, "p_att")),
        "order_blocks": randomize(BLOCKS, substream_seed(SURVEY_VERSION, seed, "blocks")),
        "excludeNonRelevant": xnr,
        "clearNonRelevantOnPage": cnr,
        "status": "started",
        "surveyVersion": SURVEY_VERSION,
    }
    save_session(s)
    return s


def session_path(sid: str) -> Path:
    if not sid.isalnum():
        raise ValueError("bad sid")
    return DATA / "sessions" / f"{sid}.json"


def save_session(s: dict) -> None:
    p = session_path(s["sid"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s, indent=1))


def load_session(sid: str) -> dict | None:
    try:
        p = session_path(sid)
    except ValueError:
        return None
    return json.loads(p.read_text()) if p.exists() else None


def inject(model_xml: str, values: dict[str, str]) -> str:
    """E4: set default values in the primary instance (first <instance>, first child)."""
    dom = minidom.parseString(model_xml)
    instance = dom.getElementsByTagName("instance")[0]
    data = next(n for n in instance.childNodes if n.nodeType == n.ELEMENT_NODE)
    for name, value in values.items():
        node = next(n for n in data.childNodes if n.nodeType == n.ELEMENT_NODE and n.tagName == name)
        while node.firstChild:
            node.removeChild(node.firstChild)
        node.appendChild(dom.createTextNode(value))
    return dom.documentElement.toxml()


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Enketo spike survey</title><link rel="stylesheet" href="/static/plain.css"></head>
<body><main class="main"><div class="paper">
{form}
<section class="form-footer">
  <div class="form-footer__content">
    <button type="button" class="btn btn-default previous-page disabled">Back</button>
    <button type="button" class="btn btn-primary next-page">Next</button>
    <button type="button" class="btn btn-primary" id="submit-form">Submit</button>
  </div>
  <p id="status" role="status" aria-live="polite"></p>
</section>
</div></main>
<script>window.__SPIKE__ = {boot};</script>
<script src="/static/{bundle}"></script>
</body></html>"""


def render(s: dict) -> str:
    pub = _load_published()
    model = inject(pub["model"], {
        "cond": s["cond"], "seed": str(s["seed"]),
        "order_att": " ".join(s["order_att"]), "order_blocks": " ".join(s["order_blocks"]),
    })
    draft = s.get("draft") or {}
    boot = {
        "sid": s["sid"], "modelStr": model, "instanceStr": draft.get("xml"), "page": draft.get("page"),
        "orderAtt": " ".join(s["order_att"]), "orderBlocks": " ".join(s["order_blocks"]),
        "excludeNonRelevant": s.get("excludeNonRelevant", False),
        "clearNonRelevantOnPage": s.get("clearNonRelevantOnPage", False),
    }
    bundle = "app-slim.js" if s.get("slim") else "app.js"
    return PAGE.format(form=pub["form"], boot=json.dumps(boot).replace("</", "<\\/"), bundle=bundle)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8", headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path.split("/") if p]
        if u.path == "/start":
            seed = int(q["seed"]) if q.get("seed", "").isdigit() else None
            s = new_session(q.get("cond"), seed, q.get("xnr") == "1", q.get("cnr") == "1")
            if q.get("slim") == "1":
                s["slim"] = True
                save_session(s)
            return self._send(303, b"", headers={"Location": f"/s/{s['sid']}"})
        if len(parts) == 2 and parts[0] == "s":
            s = load_session(parts[1])
            if not s:
                return self._send(404, b"<h1>No such session</h1>")
            if s["status"] == "complete":
                return self._send(200, b'<!doctype html><html lang="en"><title>Done</title><h1 id="already">You have already completed this survey.</h1></html>')
            return self._send(200, render(s).encode())
        if len(parts) == 2 and parts[0] == "static":
            f = DIST / parts[1]
            if f.is_file() and f.parent == DIST:
                ctype = {"js": "text/javascript", "css": "text/css"}.get(f.suffix[1:], "application/octet-stream")
                return self._send(200, f.read_bytes(), ctype)
        return self._send(404, b"not found")

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n) or b"{}")
        if len(parts) == 3 and parts[0] == "s":
            with LOCK:
                s = load_session(parts[1])
                if not s or s["status"] == "complete":
                    return self._json({"error": "closed"}, 409)
                if parts[2] == "draft":
                    s["draft"] = {"xml": body.get("xml"), "page": body.get("page")}
                    save_session(s)
                    return self._json({"ok": True})
                if parts[2] == "submit":
                    out = DATA / "submissions"
                    out.mkdir(parents=True, exist_ok=True)
                    (out / f"{s['sid']}.raw.xml").write_text(body["raw"])
                    (out / f"{s['sid']}.pruned.xml").write_text(body["pruned"])
                    (out / f"{s['sid']}.pages.json").write_text(json.dumps(body.get("pages")))
                    s["status"] = "complete"
                    s.pop("draft", None)
                    save_session(s)
                    return self._json({"ok": True, "file": html.escape(f"submissions/{s['sid']}.raw.xml")})
        return self._json({"error": "not found"}, 404)


def serve(port: int = 8765) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


if __name__ == "__main__":
    import time
    serve()
    print("serving http://127.0.0.1:8765/start")
    while True:
        time.sleep(3600)
