"""Admin-UI helpers (Playwright) for things RC2 lacks, e.g. downloading a survey's .lss export.
Used only for format exploration; the main runner is API-only."""
from __future__ import annotations

from playwright.sync_api import Page

from .rpc import ADMIN_PASSWORD, ADMIN_USER, BASE


def admin_login(page: Page) -> None:
    page.goto(f"{BASE}/index.php?r=admin/authentication/sa/login")
    page.fill("#user", ADMIN_USER)
    page.fill("#password", ADMIN_PASSWORD)
    page.click("button[name=login_submit]")
    page.wait_for_load_state("networkidle")


def export_lss(page: Page, sid: int) -> bytes:
    url = f"{BASE}/index.php?r=admin/export&sa=survey&action=exportstructurexml&surveyid={sid}"
    resp = page.request.get(url)
    return resp.body()
