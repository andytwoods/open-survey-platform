"""deploy/Dockerfile (task H2b): base images pinned by exact version and in step with the
toolchain the repo pins elsewhere (CI, web/package.json). Building the image is manual
(docs/hosting.md section 7); this keeps the pins honest without Docker."""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = (REPO / "deploy" / "Dockerfile").read_text(encoding="utf-8")
CI = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _args() -> dict[str, str]:
    return dict(re.findall(r"^ARG (\w+)=(\S+)$", DOCKERFILE, re.M))


def _ci(name: str) -> str:
    m = re.search(rf'^\s*{name}:\s*"?([^"\s]+)"?', CI, re.M)
    assert m, name
    return m.group(1)


def test_base_images_are_pinned_to_exact_versions():
    args = _args()
    images = {k: v for k, v in args.items() if k.endswith("_IMAGE")}
    assert set(images) == {"PYTHON_IMAGE", "NODE_IMAGE", "UV_IMAGE"}
    for name, ref in images.items():
        tag = ref.rsplit(":", 1)[1]
        assert re.match(r"\d+\.\d+\.\d+", tag), f"{name}={ref} is not pinned to x.y.z"
    # Every FROM goes through those arguments or an earlier stage, never a floating tag.
    for line in re.findall(r"^FROM (\S+)", DOCKERFILE, re.M):
        assert line.startswith("${") or line in {"uv", "node", "python", "web"}, line


def test_pins_match_the_rest_of_the_repo():
    args = _args()
    assert args["UV_IMAGE"].endswith(":" + _ci("UV_VERSION"))
    assert args["NODE_IMAGE"].split(":")[1].split(".")[0] == _ci("NODE_VERSION")
    assert (
        args["PYTHON_IMAGE"]
        .split(":")[1]
        .startswith((REPO / ".python-version").read_text().strip() + ".")
    )
    manager = json.loads((REPO / "web" / "package.json").read_text())["packageManager"]
    assert manager == f"pnpm@{args['PNPM_VERSION']}"


def test_runs_as_non_root_with_a_healthcheck():
    assert re.search(r"^USER osp$", DOCKERFILE, re.M)
    assert "HEALTHCHECK" in DOCKERFILE and "/api/health" in DOCKERFILE
    assert "uv sync --locked" in DOCKERFILE
    assert "--frozen-lockfile" in DOCKERFILE
