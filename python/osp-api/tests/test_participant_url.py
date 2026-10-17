"""The participant link comes from the deployment (OSP_PARTICIPANT_URL_TEMPLATE)."""

from osp_api.participant import DEFAULT_PARTICIPANT_URL, participant_url


def test_default_is_relative_runtime_path(monkeypatch):
    monkeypatch.delenv("OSP_PARTICIPANT_URL_TEMPLATE", raising=False)
    assert participant_url("ab c") == DEFAULT_PARTICIPANT_URL.replace("{slug}", "ab%20c")


def test_template_from_env(monkeypatch):
    monkeypatch.setenv("OSP_PARTICIPANT_URL_TEMPLATE", "https://take.example/r/?s={slug}")
    assert participant_url("x1") == "https://take.example/r/?s=x1"


def test_template_without_placeholder_falls_back(monkeypatch):
    monkeypatch.setenv("OSP_PARTICIPANT_URL_TEMPLATE", "https://broken.example/")
    assert participant_url("x1") == "/r/?s=x1"
