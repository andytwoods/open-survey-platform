"""AI1 guardrails: draft only (never publish), ops validated, no participant data."""

from __future__ import annotations

import anyio
import pytest
from osp_app.auth import Action
from osp_app.commands import COMMANDS
from osp_mcp.drafting import (
    ALLOWED_COMMANDS,
    BLOCKED_OPS,
    FORBIDDEN_ACTIONS,
    Drafting,
    DraftingError,
    check_guardrails,
)
from osp_ops import REGISTRY

FORBIDDEN_WORDS = ("publish", "delete", "export", "result", "response", "repro", "simulate")


def test_allowlist_is_draft_only_against_the_live_registry():
    check_guardrails()
    assert ALLOWED_COMMANDS <= set(COMMANDS)
    for cid in ALLOWED_COMMANDS:
        assert COMMANDS[cid].action not in FORBIDDEN_ACTIONS, cid
        assert COMMANDS[cid].action in (Action.SURVEY_READ, Action.SURVEY_EDIT), cid
    # Every command that publishes, deletes or reaches participant data is outside.
    outside = {cid for cid, spec in COMMANDS.items() if spec.action in FORBIDDEN_ACTIONS}
    assert {"survey.publish", "survey.delete", "survey.export_responses"} <= outside
    assert not (outside & ALLOWED_COMMANDS)
    for cid in ALLOWED_COMMANDS:
        assert not any(w in cid for w in FORBIDDEN_WORDS), cid


def test_check_guardrails_bites(monkeypatch):
    monkeypatch.setattr("osp_mcp.drafting.ALLOWED_COMMANDS", frozenset({"survey.publish"}))
    with pytest.raises(RuntimeError, match="must not expose 'survey.publish'"):
        check_guardrails()
    monkeypatch.setattr("osp_mcp.drafting.ALLOWED_COMMANDS", frozenset({"survey.nope"}))
    with pytest.raises(RuntimeError, match="unknown app command"):
        check_guardrails()


def test_forbidden_commands_are_unreachable_even_internally(drafting: Drafting):
    sid = drafting.create_survey("Guarded")["surveyId"]
    for cid in (
        "survey.publish",
        "survey.delete",
        "survey.export_responses",
        "survey.results_query",
    ):
        with pytest.raises(DraftingError, match="is not a drafting command"):
            drafting._run(cid, survey_id=sid)
    assert drafting.get_survey(sid)["publishedVersions"] == 0


def test_blocked_ops_are_refused_and_everything_else_is_a_real_op(drafting: Drafting):
    sid = drafting.create_survey("Guarded")["surveyId"]
    assert set(BLOCKED_OPS) <= set(REGISTRY)
    for op_id in BLOCKED_OPS:
        with pytest.raises(DraftingError, match=f"'{op_id}' is not allowed"):
            drafting.apply_ops(sid, [{"op": op_id, "params": {}}])
        with pytest.raises(DraftingError, match="no drafting op"):
            drafting.describe_op(op_id)
    listed = {o["id"] for o in drafting.list_ops()}
    assert listed == set(REGISTRY) - set(BLOCKED_OPS)
    assert drafting.get_survey(sid)["revision"] == 0


def test_tool_names_and_descriptions_never_offer_publishing(server):
    tools = anyio.run(server.list_tools)
    names = {t.name for t in tools}
    assert len(names) == 16
    for name in names:
        assert not any(w in name for w in FORBIDDEN_WORDS), name
    # The instructions tell the agent the boundary in plain words.
    assert "cannot publish" in server.instructions
    read_only = {t.name for t in tools if t.annotations and t.annotations.read_only_hint}
    assert {"list_surveys", "get_survey", "validate", "preview", "list_ops"} <= read_only
    assert "apply_ops" not in read_only and "create_survey" not in read_only


def test_a_viewer_role_can_read_but_not_edit(env, monkeypatch):
    """Permissions still come from osp-app: the MCP identity's role is honoured."""
    from osp_mcp.server import Settings, drafting_for, open_services

    monkeypatch.setenv("OSP_MCP_ROLE", "viewer")
    env = {**env, "OSP_MCP_ROLE": "viewer"}
    settings = Settings.from_env(env)
    viewer = drafting_for(settings, open_services(settings, env))
    with pytest.raises(DraftingError, match="Not permitted"):
        viewer.create_survey("Nope")
    assert viewer.list_surveys() == []
