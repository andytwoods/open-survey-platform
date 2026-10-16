"""``osp-cli``: a thin command-line shell over ``osp-app``.

Commands
- ``gen-key``: print a fresh ``OSP_STORE_KEYS`` value (the store's encryption keyring).
- ``seed-fixture <fixture-dir>``: migrate the database, create a lab and a researcher (or
  reuse them), import the fixture's ``survey.json`` as a new survey and publish it. Prints
  one JSON object (slug, plan URL, ids, credentials) for test harnesses such as Playwright.

The database URL comes from ``--db`` or ``OSP_DATABASE_URL``; the keyring from
``OSP_STORE_KEYS`` / ``OSP_STORE_ACTIVE_KEY`` (the same variables the server reads).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from osp_app import AppError, AppServices, build_services
from osp_app.auth import Actor, Role
from osp_app.auth.service import EmailTaken, PasswordRejected
from osp_store import (
    AccountStore,
    Keyring,
    Store,
    StoreError,
    SystemContext,
    create_engine,
    generate_key,
    migrate,
)

DEFAULT_EMAIL = "seed@osp.example"
DEFAULT_PASSWORD = "violet harbour lantern 2026"  # test data only: never a real lab
DEFAULT_LAB = "Seed lab"
SYS = SystemContext("system:seed")


class CliError(Exception):
    """A user-facing failure: printed, exit code 2."""


def _title(survey: Any, fallback: str) -> str:
    try:
        title = survey["metadata"]["title"]
        if isinstance(title, dict):
            title = next(iter(title.values()), "")
        text = str(title).strip()[:500]
        return text or fallback
    except KeyError, TypeError, AttributeError:
        return fallback


def open_services(db_url: str, environ: Mapping[str, str] | None = None) -> AppServices:
    env = os.environ if environ is None else environ
    if not env.get("OSP_STORE_KEYS"):
        raise CliError("OSP_STORE_KEYS is not set: run `osp-cli gen-key` and export its output")
    keyring = Keyring.from_env(env)
    engine = create_engine(db_url)
    migrate(engine)
    return build_services(Store(engine, keyring))


def researcher(services: AppServices, email: str, password: str, lab: str) -> Actor:
    """The seed researcher (owner of their lab), created on first use."""
    accounts = AccountStore(services.store)
    user = accounts.get_user_by_email(SYS, email)
    if user is None:
        problems = services.auth.policy.problems(password, email=email)
        if problems:  # before the lab exists, so a bad password leaves nothing behind
            raise CliError(f"password rejected: {' '.join(problems)}")
        tenant = services.store.create_tenant(SYS, lab)
        try:
            services.create_account(tenant.id, email, password, Role.OWNER)
        except PasswordRejected as exc:
            raise CliError(f"password rejected: {' '.join(exc.problems)}") from exc
        except EmailTaken as exc:  # a concurrent seed won the race
            raise CliError(f"{email} was registered meanwhile; run again") from exc
        user = accounts.get_user_by_email(SYS, email)
        assert user is not None
    memberships = services.auth.memberships.memberships_for_user(user.id)
    return Actor.from_memberships(user.id, memberships)


def seed_fixture(
    services: AppServices,
    fixture_dir: Path,
    *,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
    lab: str = DEFAULT_LAB,
    save_mode: str = "every-page",
) -> dict[str, Any]:
    path = fixture_dir / "survey.json"
    try:
        survey = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliError(f"can't read {path}: {exc}") from exc
    actor = researcher(services, email, password, lab)
    builder = services.builder
    view = builder.run(
        "survey.create", actor, title=_title(survey, fixture_dir.name), survey=survey
    )
    pub = builder.run("survey.publish", actor, survey_id=view.survey.id, save_mode=save_mode)
    return {
        "fixture": fixture_dir.name,
        "tenantId": next(iter(actor.roles)),
        "userId": actor.user_id,
        "email": email,
        "password": password,
        "surveyId": view.survey.id,
        "slug": pub.slug,
        "versionId": pub.version_id,
        "versionNumber": pub.number,
        "planChecksum": pub.plan_checksum,
        "planUrl": f"/api/s/{pub.slug}/plan/{pub.plan_checksum}",
        "startUrl": f"/api/s/{pub.slug}/sessions",
        "saveMode": pub.runtime_config["saveMode"],
    }


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="osp-cli", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("gen-key", help="print a fresh OSP_STORE_KEYS value")
    s = sub.add_parser("seed-fixture", help="import a fixture survey and publish it")
    s.add_argument("fixture_dir", type=Path, help="e.g. fixtures/16-assign")
    s.add_argument("--db", default=os.environ.get("OSP_DATABASE_URL"), help="database URL")
    s.add_argument("--email", default=DEFAULT_EMAIL)
    s.add_argument("--password", default=DEFAULT_PASSWORD)
    s.add_argument("--lab", default=DEFAULT_LAB, help="lab name, if the researcher is new")
    s.add_argument("--save-mode", choices=("every-page", "end-only"), default="every-page")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "gen-key":
        print(f"OSP_STORE_KEYS=k1:{generate_key()}")
        return 0
    try:
        if not args.db:
            raise CliError("give --db or set OSP_DATABASE_URL (e.g. sqlite:///.build/e2e.db)")
        out = seed_fixture(
            open_services(args.db),
            args.fixture_dir,
            email=args.email,
            password=args.password,
            lab=args.lab,
            save_mode=args.save_mode,
        )
    except CliError as exc:
        print(f"osp-cli: {exc}", file=sys.stderr)
        return 2
    except AppError as exc:
        detail = [d.message for d in getattr(exc, "diagnostics", []) if d.severity == "error"]
        print(f"osp-cli: {exc}" + "".join(f"\n  {m}" for m in detail[:10]), file=sys.stderr)
        return 2
    except StoreError as exc:
        print(f"osp-cli: store: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
