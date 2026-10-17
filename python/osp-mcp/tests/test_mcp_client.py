"""A scripted MCP client drives the server: in-process, and as a real stdio subprocess.

The worked example in ``docs/ai-drafting.md`` is replayed call by call (every ```json block
holding ``{"tool", "arguments"}``), so the documentation is proven, not just written.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import types
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters, get_default_environment

REPO = Path(__file__).resolve().parents[3]
DOCS_PAGE = REPO / "docs" / "ai-drafting.md"
_FENCE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


def docs_calls() -> list[dict[str, Any]]:
    calls = []
    for block in _FENCE.findall(DOCS_PAGE.read_text(encoding="utf-8")):
        try:
            data = json.loads(block)
        except ValueError:
            continue  # the client-config example, not a tool call
        if isinstance(data, dict) and {"tool", "arguments"} <= set(data):
            calls.append(data)
    return calls


def _subst(value: Any, survey_id: str) -> Any:
    if isinstance(value, str):
        return value.replace("$SURVEY", survey_id)
    if isinstance(value, list):
        return [_subst(v, survey_id) for v in value]
    if isinstance(value, dict):
        return {k: _subst(v, survey_id) for k, v in value.items()}
    return value


def _text(result: types.CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))


def _data(result: types.CallToolResult) -> Any:
    assert not result.is_error, _text(result)
    sc = result.structured_content
    if isinstance(sc, dict) and set(sc) == {"result"}:
        return sc["result"]  # a list return, wrapped by the SDK
    return sc


async def _replay_docs(client: Client) -> dict[str, Any]:
    calls = docs_calls()
    assert len(calls) >= 10 and calls[0]["tool"] == "create_survey"
    survey_id = ""
    results: dict[str, Any] = {}
    for call in calls:
        res = await client.call_tool(call["tool"], _subst(call["arguments"], survey_id))
        data = _data(res)
        if call["tool"] == "create_survey":
            survey_id = data["surveyId"]
        results[call["tool"]] = data
    results["surveyId"] = survey_id
    return results


def test_in_process_client_lists_and_calls_tools(server):
    async def main():
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            names = [t.name for t in tools]
            assert "create_survey" in names and "apply_ops" in names and len(names) == 16
            add_q = next(t for t in tools if t.name == "add_question")
            props = add_q.input_schema["properties"]
            assert set(props) == {"survey_id", "page", "question", "index"}
            assert "QuestionSpec" in json.dumps(add_q.input_schema)

            made = _data(await client.call_tool("create_survey", {"title": "From MCP"}))
            sid = made["surveyId"]
            assert made["builderUrl"] == f"http://builder.test/surveys/{sid}"
            listed = _data(await client.call_tool("list_surveys", {}))
            assert [s["surveyId"] for s in listed] == [sid]

            # A refusal is an MCP error result with the diagnostics in the text.
            bad = await client.call_tool(
                "apply_ops",
                {"survey_id": sid, "ops": [{"op": "add_question", "params": {"page": "zzz"}}]},
            )
            assert bad.is_error and "zzz" in _text(bad) and "[error]" in _text(bad)
            blocked = await client.call_tool(
                "apply_ops", {"survey_id": sid, "ops": [{"op": "set_hooks", "params": {}}]}
            )
            assert blocked.is_error and "custom code" in _text(blocked)
            # Bad argument shapes are refused by the SDK's schema check, never a crash.
            shape = await client.call_tool("add_question", {"survey_id": sid, "page": 3})
            assert shape.is_error
            missing = await client.call_tool("get_survey", {"survey_id": "no-such-survey"})
            assert missing.is_error and "Survey not found" in _text(missing)
            unknown = await client.call_tool("publish_survey", {"survey_id": sid})
            assert unknown.is_error
            assert _data(await client.call_tool("get_survey", {"survey_id": sid}))["revision"] == 0

    anyio.run(main)


def test_docs_worked_example_replays_in_process(server, drafting):
    async def main():
        async with Client(server) as client:
            return await _replay_docs(client)

    out = anyio.run(main)
    sid = out["surveyId"]
    v = out["validate"]
    assert v["valid"] is True and v["problems"]["errors"] == 0 and v["publishChecks"] == []
    p = out["preview"]
    assert p["compiles"] is True and p["pages"] == 4 and p["items"] == 8  # matrix rows are items
    assert p["builderUrl"] == f"http://builder.test/surveys/{sid}"
    full = drafting.get_survey(sid, full=True)["survey"]
    assert [b["id"] for b in full["blocks"]] == ["b1", "screening", "habits", "sleep"]
    assert [n["block"] for n in full["flow"]] == ["b1", "screening", "habits", "sleep"]
    habits = full["blocks"][2]["pages"][0]
    assert habits["showIf"]["kind"] == "compare" and habits["title"] == "Your coffee"
    cups = habits["items"][0]
    assert cups["constraint"]["kind"] == "compare" and cups["constraintMessage"]
    assert [c["label"] for c in habits["items"][1]["choices"]][-1] == "Night"
    assert full["settings"]["retention"] == {"kind": "days-after-close", "days": 90}
    assert full["consent"]["agreeLabel"] == "I agree to take part"
    # Drafted, never published.
    assert drafting.get_survey(sid)["publishedVersions"] == 0
    kinds = [h["kind"] for h in drafting.history(sid)]
    assert kinds and set(kinds) == {"edit"}


@pytest.mark.skipif(
    sys.platform == "win32" and not os.environ.get("SYSTEMROOT"),
    reason="a Windows subprocess needs SYSTEMROOT",
)
def test_stdio_subprocess_server(env):
    """The real transport: launch ``python -m osp_mcp.server`` and talk MCP over its pipes."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "osp_mcp.server"],
        env={**get_default_environment(), "PYTHONUTF8": "1", **env},
        cwd=str(REPO),
    )

    async def main():
        async with Client(params) as client:
            assert client.server_info is not None
            assert client.server_info.name == "open-survey-platform"
            assert "cannot publish" in (client.instructions or "")
            names = {t.name for t in (await client.list_tools()).tools}
            assert {"create_survey", "add_block", "validate", "preview", "undo"} <= names
            made = _data(await client.call_tool("create_survey", {"title": "Over stdio"}))
            r = _data(
                await client.call_tool(
                    "add_question",
                    {
                        "survey_id": made["surveyId"],
                        "page": "p1",
                        "question": {
                            "id": "mood",
                            "type": "single",
                            "label": "How do you feel?",
                            "choices": ["Good", "Bad"],
                        },
                    },
                )
            )
            assert r["revision"] == 1
            undone = _data(
                await client.call_tool(
                    "undo", {"survey_id": made["surveyId"], "transaction_id": r["transactionId"]}
                )
            )
            assert undone["revision"] == 2
            assert len(undone["outline"]["blocks"][0]["pages"][0]["items"]) == 1
            return made["surveyId"]

    sid = anyio.run(main)
    # The subprocess wrote to the same database: a second process sees the survey.
    from osp_mcp.server import Settings, drafting_for, open_services

    settings = Settings.from_env(env)
    d = drafting_for(settings, open_services(settings, env))
    assert [s["surveyId"] for s in d.list_surveys()] == [sid]


def test_bad_config_is_a_message_not_a_traceback(env, monkeypatch, capsys):
    from osp_mcp.server import main

    monkeypatch.delenv("OSP_MCP_USER")
    assert main([]) == 2 and "OSP_MCP_USER must be set" in capsys.readouterr().err
    monkeypatch.setenv("OSP_MCP_USER", "bad:user")
    assert main([]) == 2 and "user id" in capsys.readouterr().err
    monkeypatch.setenv("OSP_MCP_USER", "ok-user")
    monkeypatch.setenv("OSP_MCP_ROLE", "admin")
    assert main([]) == 2 and "role must be one of" in capsys.readouterr().err
    monkeypatch.setenv("OSP_MCP_ROLE", "editor")
    monkeypatch.setenv("OSP_MCP_BUILDER_URL", "http://x/no-placeholder")
    assert main([]) == 2 and "{id}" in capsys.readouterr().err
    monkeypatch.delenv("OSP_MCP_BUILDER_URL")
    monkeypatch.setenv("OSP_DATABASE_URL", "nonsense://")
    assert main([]) == 2 and "OSP_DATABASE_URL" in capsys.readouterr().err
    assert main(["bogus"]) == 2 and "usage" in capsys.readouterr().err


def test_tools_subcommand_needs_no_database(monkeypatch, capsys):
    from osp_mcp.server import main

    for var in ("OSP_DATABASE_URL", "OSP_STORE_KEYS", "OSP_MCP_USER", "OSP_MCP_LAB"):
        monkeypatch.delenv(var, raising=False)
    assert main(["tools"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert {t["name"] for t in listing} >= {"create_survey", "apply_ops", "validate"}
    assert all(t["description"] for t in listing)
