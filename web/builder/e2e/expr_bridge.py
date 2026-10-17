"""Answers /api/meta/expressions/{parse,print} for the condition builder e2e tests.

Reads one JSON request per line on stdin ({"path": "parse"|"print", "body": {...}}) and
writes one JSON response per line, using osp-api's own handler functions, so the browser
sees exactly what the server would answer (minus sign-in). A request with a surveyId is
checked against the /dev/conditions sample survey.

    uv run --locked python web/builder/e2e/expr_bridge.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from osp_api.routes.expressions import parse_expression, print_expression
from osp_spec import validate

SURVEY_FILE = Path(__file__).parents[1] / "src/dev/conditions/sample-survey.json"


def main() -> None:
    survey = json.loads(SURVEY_FILE.read_text())
    errors = [d for d in validate(survey) if d.severity == "error"]
    if errors:
        raise SystemExit(f"sample survey is invalid: {errors}")
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        req = json.loads(line)
        body = req.get("body") or {}
        if req.get("path") == "print":
            res = print_expression(body.get("ast"))
        else:
            res = parse_expression(
                body.get("text", ""),
                survey if body.get("surveyId") else None,
                body.get("target"),
                body.get("field"),
            )
        print(json.dumps(res.model_dump(mode="json")), flush=True)


if __name__ == "__main__":
    main()
