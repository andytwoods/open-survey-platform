"""A throwaway SQLite store and one configured researcher for every osp-mcp test."""

from __future__ import annotations

import pytest
from osp_mcp.drafting import Drafting
from osp_mcp.server import Settings, build_server, drafting_for, open_services
from osp_store import generate_key

USER = "mcp-researcher"  # test data only
LAB = "mcp-lab"


@pytest.fixture
def env(tmp_path, monkeypatch) -> dict[str, str]:
    values = {
        "OSP_DATABASE_URL": f"sqlite:///{tmp_path / 'mcp.db'}",
        "OSP_STORE_KEYS": f"k1:{generate_key()}",
        "OSP_MCP_USER": USER,
        "OSP_MCP_LAB": LAB,
        "OSP_MCP_ROLE": "editor",
        "OSP_MCP_BUILDER_URL": "http://builder.test/surveys/{id}",
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("OSP_STORE_ACTIVE_KEY", raising=False)
    monkeypatch.delenv("OSP_MCP_NAME", raising=False)
    return values


@pytest.fixture
def settings(env) -> Settings:
    return Settings.from_env(env)


@pytest.fixture
def services(settings, env):
    return open_services(settings, env)


@pytest.fixture
def drafting(settings, services) -> Drafting:
    return drafting_for(settings, services)


@pytest.fixture
def server(drafting):
    return build_server(drafting)
