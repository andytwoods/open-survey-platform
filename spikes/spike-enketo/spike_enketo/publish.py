"""Publish step: XLSForm (.md) -> pyxform -> XForm XML -> enketo-transformer (browser build, run
in headless WebKit (Chromium 156 injects an XSLT deprecation banner into the output) because the Node build needs the native `libxslt` addon, which does not
compile on Node 24) -> build/<form>.json {form, model, transformerVersion}."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "survey/spike_enketo.md"
BUILD = ROOT / "build"


def xlsform_to_xform() -> Path:
    BUILD.mkdir(exist_ok=True)
    out = BUILD / "spike_enketo.xml"
    subprocess.run([sys.executable, "-m", "pyxform.xls2xform", str(SRC), str(out)], check=True, capture_output=True)
    return out


def transform_in_browser(xform_path: Path, engine: str = "webkit") -> dict:
    xform = xform_path.read_text()
    with sync_playwright() as p:
        b = getattr(p, engine).launch()
        page = b.new_page()
        page.goto("about:blank")
        page.add_script_tag(path=str(ROOT / "web/dist/transformer.js"))
        t0 = time.perf_counter()
        res = page.evaluate(
            "async (xform) => { const r = await window.enketoTransform.transform({ xform, theme: 'plain' });"
            " return { form: r.form, model: r.model, transformerVersion: r.transformerVersion, languageMap: r.languageMap }; }",
            xform,
        )
        res["transformMs"] = round((time.perf_counter() - t0) * 1000)
        res["browser"] = f"{engine} {b.version}"
        b.close()
    res["xformSha256"] = hashlib.sha256(xform.encode()).hexdigest()
    return res


def main() -> dict:
    xml = xlsform_to_xform()
    res = transform_in_browser(xml)
    (BUILD / "spike_enketo.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = main()
    print(f"published: transformer {r['transformerVersion']} in {r['transformMs']} ms, {r['browser']}, form {len(r['form'])} chars")
