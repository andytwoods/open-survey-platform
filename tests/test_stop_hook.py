"""S5 acceptance: an agent session can't finish with a failing check.

Runs scripts/stop-hook.sh against a throwaway git repo with a fake check command
(OSP_STOP_HOOK_CMD), feeding it the JSON Claude Code sends on stdin.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "scripts" / "stop-hook.sh"
# Windows can't exec a shell script directly (WinError 193): run it through Git Bash,
# which Claude Code's hooks use there too. Skipped when no bash is on PATH.
BASH = shutil.which("bash")
HOOK_CMD = [str(HOOK)] if os.name != "nt" else [BASH or "bash", str(HOOK)]
pytestmark = pytest.mark.skipif(
    os.name == "nt" and not BASH, reason="stop-hook.sh needs bash (Git Bash on Windows)"
)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    for args in (
        ["init", "-q", "-b", "agent/test"],
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=r, check=True)
    (r / ".gitignore").write_text(".claude/.stop-hook-*\n")
    (r / "a.txt").write_text("a\n")
    _commit(r, "init")
    return r


def _commit(r: Path, msg: str):
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=r, check=True)


class Hook:
    def __init__(self, repo: Path, tmp: Path):
        self.repo = repo
        self.ran = tmp / "ran.log"  # outside the repo, so it never dirties the tree
        self.passing = False

    def __call__(self, *, active=False, mode=None):
        verdict = "exit 0" if self.passing else "echo 'FAILED: test_widget' >&2; exit 1"
        env = {
            **os.environ,
            "OSP_STOP_HOOK_CMD": f"echo ran >> '{self.ran}'; echo 'checking'; {verdict}",
            "OSP_STOP_HOOK_MAX_BLOCKS": "3",
        }
        env.pop("CLAUDE_PROJECT_DIR", None)
        payload = {"session_id": "x", "cwd": str(self.repo), "stop_hook_active": active}
        return subprocess.run(
            [*HOOK_CMD, *([mode] if mode else [])],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            cwd=self.repo.parent,
        )

    @property
    def runs(self) -> int:
        return len(self.ran.read_text().splitlines()) if self.ran.exists() else 0


@pytest.fixture
def hook(repo, tmp_path):
    return Hook(repo, tmp_path)


def test_chat_only_session_is_not_blocked(hook):
    assert hook(mode="session-start").returncode == 0
    result = hook()
    assert result.returncode == 0
    assert hook.runs == 0  # check not even run


def test_dirty_tree_with_failing_check_blocks(hook, repo):
    hook(mode="session-start")
    (repo / "a.txt").write_text("changed\n")
    result = hook()
    assert result.returncode == 2
    assert "FAILED: test_widget" in result.stderr
    assert "attempt 1/3" in result.stderr


def test_new_commit_with_failing_check_blocks(hook, repo):
    hook(mode="session-start")
    (repo / "b.txt").write_text("b\n")
    _commit(repo, "work")
    assert hook().returncode == 2


def test_untracked_file_counts_as_a_change(hook, repo):
    hook(mode="session-start")
    (repo / "new.py").write_text("x = 1\n")
    assert hook().returncode == 2


def test_passing_check_allows_and_stamps(hook, repo):
    hook(mode="session-start")
    (repo / "b.txt").write_text("b\n")
    _commit(repo, "work")
    hook.passing = True
    assert hook().returncode == 0
    assert hook.runs == 1
    # Nothing changed since the green check: skipped, even if the check would now fail.
    hook.passing = False
    assert hook().returncode == 0
    assert hook.runs == 1


def test_loop_guard_honours_stop_hook_active(hook, repo):
    hook(mode="session-start")
    (repo / "a.txt").write_text("changed\n")
    assert hook(active=False).returncode == 2  # attempt 1
    assert hook(active=True).returncode == 2  # attempt 2
    assert hook(active=True).returncode == 2  # attempt 3
    final = hook(active=True)  # would be attempt 4: give up rather than loop forever
    assert final.returncode == 0
    assert "blocked" in final.stderr
    # A fresh stop (not hook-driven) starts counting again.
    assert hook(active=False).returncode == 2


def test_outside_a_git_repo_does_nothing(tmp_path):
    payload = json.dumps({"cwd": str(tmp_path), "stop_hook_active": False})
    env = {**os.environ, "OSP_STOP_HOOK_CMD": "exit 1"}
    env.pop("CLAUDE_PROJECT_DIR", None)
    result = subprocess.run(
        HOOK_CMD, input=payload, capture_output=True, text=True, env=env, cwd=tmp_path
    )
    assert result.returncode == 0


def test_settings_wire_the_hook():
    settings = json.loads((HOOK.parents[1] / ".claude" / "settings.json").read_text())
    stop = settings["hooks"]["Stop"][0]["hooks"][0]
    assert stop["command"].endswith("scripts/stop-hook.sh")
    start = settings["hooks"]["SessionStart"][0]["hooks"][0]
    assert start["command"].endswith("scripts/stop-hook.sh session-start")
