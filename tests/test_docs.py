"""Docs site (task D2): the API reference is rendered from the committed contract.

`make docs-check` (in `make check`) proves the whole site builds in strict mode; this
pins down the generator itself, so a change to the contract's shape fails here with a
clear message rather than as a missing anchor in an MkDocs build.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "docs_openapi.py"

_spec = importlib.util.spec_from_file_location("docs_openapi", SCRIPT)
gen = importlib.util.module_from_spec(_spec)
sys.modules["docs_openapi"] = gen
_spec.loader.exec_module(gen)


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads((REPO / "contract" / "openapi.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page(contract) -> str:
    return gen.render(contract)


def test_every_operation_and_schema_has_a_heading(contract, page):
    ids = set(re.findall(r"\{ #([A-Za-z0-9_-]+) \}", page))
    for item in contract["paths"].values():
        for method in gen.METHODS:
            if method in item:
                assert item[method]["operationId"] in ids
    for name in contract["components"]["schemas"]:
        assert name in ids


def test_internal_links_resolve(page):
    ids = set(re.findall(r"\{ #([A-Za-z0-9_-]+) \}", page))
    targets = set(re.findall(r"\]\(#([A-Za-z0-9_-]+)\)", page))
    assert targets <= ids, sorted(targets - ids)


def test_parameters_and_responses_are_rendered(page):
    # exportResponses has query parameters with enums and defaults, and a CSV response.
    section = page.split("{ #exportResponses }")[1].split("### ")[0]
    assert "| `format` | query |" in section
    assert '`"csv"` \\| `"json"`' in section
    assert "text/csv" in section


def test_type_strings():
    assert gen.type_str({"type": "string", "format": "date-time"}) == "string (date-time)"
    assert gen.type_str({"$ref": "#/components/schemas/Card"}) == "[Card](#Card)"
    assert gen.type_str({"anyOf": [{"type": "integer"}, {"type": "null"}]}) == "integer \\| null"
    assert gen.type_str({"type": "array", "items": {"type": "number"}}) == "array of number"
    assert gen.type_str({"enum": ["a", "b"]}) == '`"a"` \\| `"b"`'
    assert gen.type_str({"type": "object", "additionalProperties": {"type": "string"}}) == (
        "object of string"
    )
    assert gen.type_str(None) == "any"


def test_cells_never_break_tables():
    assert gen._cell("a | b\nc") == "a \\| b c"


def test_mkdocs_hook_adds_the_page(contract):
    """The hook signature MkDocs calls: `on_files(files, config)`."""
    mkdocs = pytest.importorskip("mkdocs")
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import Files

    assert mkdocs.__version__ >= "1.6"
    config = MkDocsConfig(config_file_path=str(REPO / "mkdocs.yml"))
    config.load_dict({"site_name": "t", "docs_dir": str(REPO / "docs")})
    errors, _warnings = config.validate()
    assert not errors
    # `File.generated` names the plugin running the event; a build sets this in `run_event`.
    config.plugins._current_plugin = None
    files = gen.on_files(Files([]), config)
    (f,) = list(files)
    assert f.src_uri == gen.PAGE
    assert "# Open Survey Platform API" in f.content_string
