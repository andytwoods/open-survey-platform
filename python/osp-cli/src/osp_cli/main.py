"""``osp-cli``: a thin command-line shell over ``osp-app``.

Commands
- ``gen-key``: print a fresh ``OSP_STORE_KEYS`` value (the store's encryption keyring).
- ``lab create <lab-id> [--name N]``: create a lab with the host's id (needed first when
  ``OSP_AUTO_CREATE_LABS=off``).
- ``seed-fixture <fixture-dir>``: migrate the database, make sure the lab exists, import the
  fixture's ``survey.json`` as a new survey owned by ``--user`` and publish it. Prints one
  JSON object (slug, plan URL, ids) for test harnesses such as Playwright.
- ``dev-seed <fixture-dir>...`` (``make dev``, dev only): on the first run, seed each fixture
  into the dev lab as the dev researcher (``osp_app.identity``: the identity osp-api's Dev
  provider uses, so no sign-in); remember it in ``<data-dir>/dev-seed.json`` (gitignored).
  Every run prints the builder and participant links. Refused when ``OSP_ENV=production``.
  On the first run with ``OSP_ENV=dev`` it also fills each seeded survey with fake responses
  (150 each; ``DEV_FAKE_RESPONSES=<n>`` changes the count, ``0`` turns it off).
- ``fake-responses <survey id or slug>... [--n 150] [--seed 1] [--partial 0.15] [--days 21]``
  (dev only, ``OSP_ENV=dev``; ``fake_responses.py``): invented, realistic responses made by
  the real engine and stored through the participant session service. ``--dev-seeded``
  takes the surveys from ``<data-dir>/dev-seed.json`` (``make dev-fake N=200``).
- ``backfill-outcomes``: one-off after migration 0011 (task EN4): give every stored
  response without an ``outcome`` column the end outcome inside its record, so the results
  page counts per outcome without decrypting. Reads each such record once; re-running is a
  no-op. Prints ``{"scanned": n, "updated": n}``.

There are no accounts or passwords (plan P): the host owns sign-in.

The database URL comes from ``--db`` or ``OSP_DATABASE_URL``; the keyring from
``OSP_STORE_KEYS`` / ``OSP_STORE_ACTIVE_KEY`` (the same variables the server reads).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from osp_app import AppError, AppServices, InvalidIdentity, build_services, make_identity
from osp_app.auth import Actor, Role
from osp_app.identity import DEV_LAB_ID, DEV_USER_ID, check_tenant_id
from osp_store import (
    DatabaseUrlError,
    Keyring,
    ParticipantStore,
    Store,
    StoreError,
    SystemContext,
    create_engine,
    generate_key,
    migrate,
)

from .fake_responses import FakeError, fake_responses

DEFAULT_USER = "seed-researcher"  # test data only: never a real lab
DEFAULT_LAB = "seed-lab"


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
    try:
        engine = create_engine(db_url)
    except DatabaseUrlError as exc:
        raise CliError(f"database URL: {exc}") from exc
    migrate(engine)
    return build_services(Store(engine, keyring))


def researcher(services: AppServices, user_id: str, lab: str) -> Actor:
    """``user_id`` as the owner of ``lab`` (created if missing), as a host would say."""
    try:
        identity = make_identity(user_id, {lab: Role.OWNER})
    except InvalidIdentity as exc:
        raise CliError(str(exc)) from exc
    services.create_lab(lab)
    return services.admit(identity)


# Retention the seed sets on a fixture survey without one (synthetic data only).
SEED_RETENTION = {"kind": "days-after-close", "days": 30}


def seed_fixture(
    services: AppServices,
    fixture_dir: Path,
    *,
    user: str = DEFAULT_USER,
    lab: str = DEFAULT_LAB,
    save_mode: str | None = None,
) -> dict[str, Any]:
    path = fixture_dir / "survey.json"
    try:
        survey = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliError(f"can't read {path}: {exc}") from exc
    if isinstance(survey, dict) and "retention" not in (survey.get("settings") or {}):
        # Publishing requires an explicit retention policy. Fixtures hold synthetic data
        # only, so the seed chooses one explicitly (and says so in its output).
        survey["settings"] = {**(survey.get("settings") or {}), "retention": SEED_RETENTION}
    actor = researcher(services, user, lab)
    builder = services.builder
    view = builder.run(
        "survey.create", actor, title=_title(survey, fixture_dir.name), survey=survey
    )
    pub = builder.run("survey.publish", actor, survey_id=view.survey.id, save_mode=save_mode)
    return {
        "fixture": fixture_dir.name,
        "tenantId": next(iter(actor.roles)),
        "userId": actor.user_id,
        "surveyId": view.survey.id,
        "slug": pub.slug,
        "versionId": pub.version_id,
        "versionNumber": pub.number,
        "planChecksum": pub.plan_checksum,
        "planUrl": f"/api/s/{pub.slug}/plan/{pub.plan_checksum}",
        "startUrl": f"/api/s/{pub.slug}/sessions",
        "saveMode": pub.runtime_config["saveMode"],
    }


DEV_SEED_FILE = "dev-seed.json"


DEV_FAKE_DEFAULT = 150


def dev_fake_count(environ: Mapping[str, str] | None = None) -> int:
    """Fake responses per seeded survey on the first ``make dev``: ``DEV_FAKE_RESPONSES``
    (default 150; 0 turns it off). Only with ``OSP_ENV=dev``."""
    env = os.environ if environ is None else environ
    if (env.get("OSP_ENV") or "").strip().lower() != "dev":
        return 0
    raw = (env.get("DEV_FAKE_RESPONSES") or "").strip()
    if not raw:
        return DEV_FAKE_DEFAULT
    try:
        return max(0, int(raw))
    except ValueError as exc:
        raise CliError(f"DEV_FAKE_RESPONSES must be a number, not {raw!r}") from exc


def dev_seed(
    services_factory: Callable[[], AppServices],
    data_dir: Path,
    fixture_dirs: Sequence[Path],
    environ: Mapping[str, str] | None = None,
    fake: Callable[[str], str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """The dev lab's seeded surveys: from ``<data_dir>/dev-seed.json`` if present,
    else created now (``services_factory()`` is only called then). Returns (state, created).
    On creation, ``fake(survey_id)`` (if given) fills each survey with fake responses and
    returns a one-line summary for the banner."""
    env = os.environ if environ is None else environ
    if (env.get("OSP_ENV") or "dev").strip().lower() == "production":
        raise CliError("dev-seed is for local development only (OSP_ENV=production)")
    path = data_dir / DEV_SEED_FILE
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CliError(f"can't read {path} ({exc}); run `make dev-reset`") from exc
        if not isinstance(state, dict) or state.get("lab") != DEV_LAB_ID:
            raise CliError(
                f"{path} is from before host-owned sign-in (plan P); run `make dev-reset`"
            )
        return state, False
    services = services_factory()
    surveys = []
    for fixture in fixture_dirs:
        out = seed_fixture(services, fixture, user=DEV_USER_ID, lab=DEV_LAB_ID)
        title = _title(json.loads((fixture / "survey.json").read_text("utf-8")), fixture.name)
        keep = ("fixture", "surveyId", "slug", "planUrl", "versionNumber")
        surveys.append({k: out[k] for k in keep} | {"title": title})
    state = {"user": DEV_USER_ID, "lab": DEV_LAB_ID, "surveys": surveys}
    data_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    if fake is not None:
        for s in surveys:
            try:
                s["fake"] = fake(s["surveyId"])
            except (FakeError, CliError, AppError, StoreError) as exc:
                s["fake"] = f"no fake responses ({exc})"
    return state, True


def dev_banner(
    state: Mapping[str, Any],
    created: bool,
    *,
    builder_url: str,
    api_url: str,
    participant_link: str | None,
) -> str:
    first = " (first run: dev surveys created)" if created else ""
    lines = [
        "",
        "Open Survey Platform: local dev" + first,
        "",
        f"  Builder      {builder_url}",
        f"  API health   {api_url}/api/health",
        f"  API docs     {api_url}/api/docs",
        "",
        f"  No sign-in: everyone is {state['user']}, owner of {state['lab']} (dev only)",
        "",
        "  Seeded surveys",
    ]
    for s in state.get("surveys", []):
        lines.append(f"    {s['title']}  ({s['fixture']})")
        lines.append(f"      builder      {builder_url}/surveys/{s['surveyId']}")
        if s.get("fake"):
            lines.append(f"      responses    {s['fake']}")
        if participant_link:
            link = participant_link.replace("{slug}", s["slug"])
            lines.append(f"      participant  {link}")
        else:
            lines.append(f"      plan (API)   {api_url}{s['planUrl']}")
    if not participant_link:
        lines.append("    participant app not built yet")
    lines += [
        "",
        "  Ctrl+C stops everything. `make dev-fake N=200` adds fake responses;",
        "  `make dev-reset` wipes .data/.",
        "",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="osp-cli", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("gen-key", help="print a fresh OSP_STORE_KEYS value")
    s = sub.add_parser("seed-fixture", help="import a fixture survey and publish it")
    s.add_argument("fixture_dir", type=Path, help="e.g. fixtures/16-assign")
    s.add_argument("--db", default=os.environ.get("OSP_DATABASE_URL"), help="database URL")
    s.add_argument("--user", default=DEFAULT_USER, help="the host user id to act as (owner)")
    s.add_argument("--lab", default=DEFAULT_LAB, help="lab id, created if missing")
    s.add_argument(
        "--save-mode",
        choices=("every-page", "end-only"),
        default=None,
        help="override the survey's settings.saveMode",
    )
    lab = sub.add_parser("lab", help="labs (tenants) by the host's lab id")
    lab_sub = lab.add_subparsers(dest="lab_command", required=True)
    lc = lab_sub.add_parser("create", help="create a lab (when OSP_AUTO_CREATE_LABS=off)")
    lc.add_argument("lab_id")
    lc.add_argument("--name", default=None, help="display name (default: the id)")
    lc.add_argument("--db", default=os.environ.get("OSP_DATABASE_URL"), help="database URL")
    d = sub.add_parser("dev-seed", help="dev only: seed fixtures into the dev lab")
    d.add_argument("fixture_dirs", type=Path, nargs="+")
    d.add_argument("--db", default=os.environ.get("OSP_DATABASE_URL"), help="database URL")
    d.add_argument("--data-dir", type=Path, default=Path(os.environ.get("OSP_DATA_DIR") or ".data"))
    d.add_argument("--builder-url", default="http://localhost:5173")
    d.add_argument("--api-url", default="http://localhost:8000")
    d.add_argument(
        "--participant-link",
        default="",
        help="participant link template with {slug}; empty: the app is not built",
    )
    f = sub.add_parser(
        "fake-responses", help="dev only: invented, realistic responses for a published survey"
    )
    f.add_argument("targets", nargs="*", help="survey id (in --lab) or public slug")
    f.add_argument(
        "--dev-seeded",
        action="store_true",
        help="every survey in <data-dir>/dev-seed.json (what make dev seeded)",
    )
    f.add_argument("--n", type=int, default=150, help="sessions per survey (default 150)")
    f.add_argument("--seed", type=int, default=1, help="same seed, same responses (default 1)")
    f.add_argument(
        "--partial", type=float, default=0.15, help="share that drops out part-way (0.15)"
    )
    f.add_argument("--days", type=float, default=21, help="spread over this many days (21)")
    f.add_argument("--lab", default=DEV_LAB_ID, help="lab of the survey ids")
    f.add_argument("--db", default=os.environ.get("OSP_DATABASE_URL"), help="database URL")
    f.add_argument("--data-dir", type=Path, default=Path(os.environ.get("OSP_DATA_DIR") or ".data"))
    b = sub.add_parser(
        "backfill-outcomes",
        help="one-off after migration 0011: fill responses.outcome from each stored record",
    )
    b.add_argument("--db", default=os.environ.get("OSP_DATABASE_URL"), help="database URL")
    b.add_argument("--batch", type=int, default=500, help="records decrypted per batch (500)")
    return p


def store_factory(db_url: str, environ: Mapping[str, str] | None = None) -> Callable[..., Store]:
    """Opens the store on a given clock (fake responses carry their own times)."""
    env = os.environ if environ is None else environ
    if not env.get("OSP_STORE_KEYS"):
        raise CliError("OSP_STORE_KEYS is not set: run `osp-cli gen-key` and export its output")
    keyring = Keyring.from_env(env)

    def open_store(clock: Callable[[], Any] | None = None) -> Store:
        engine = create_engine(db_url)
        migrate(engine)
        return Store(engine, keyring) if clock is None else Store(engine, keyring, clock)

    return open_store


def _dev_targets(data_dir: Path) -> list[str]:
    path = data_dir / DEV_SEED_FILE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return [str(s["surveyId"]) for s in state["surveys"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CliError(f"can't read {path} ({exc}); run `make dev` first") from exc


def run_backfill(args: argparse.Namespace) -> int:
    """``backfill-outcomes``: migrate, then fill ``responses.outcome`` from the records."""
    if args.batch < 1:
        raise CliError("--batch must be at least 1")
    store = store_factory(args.db)()
    report = ParticipantStore(store).backfill_outcomes(
        SystemContext("system:backfill"), batch=args.batch
    )
    print(json.dumps({"scanned": report.scanned, "updated": report.updated}))
    return 0


def run_fake(args: argparse.Namespace) -> int:
    targets = list(args.targets) + (_dev_targets(args.data_dir) if args.dev_seeded else [])
    if not targets:
        raise CliError("give a survey id or slug, or --dev-seeded")
    factory = store_factory(args.db)
    for target in targets:
        report = fake_responses(
            factory,
            target,
            n=args.n,
            seed=args.seed,
            partial=args.partial,
            days=args.days,
            lab=args.lab,
        )
        print(f"fake-responses {target} (/s/{report.slug}): {report.line()}")
        print(json.dumps(report.summary()))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "gen-key":
        print(f"OSP_STORE_KEYS=k1:{generate_key()}")
        return 0
    try:
        if not args.db:
            raise CliError("give --db or set OSP_DATABASE_URL (e.g. sqlite:///.build/e2e.db)")
        if args.command == "lab":
            try:
                lab_id = check_tenant_id(args.lab_id)
            except InvalidIdentity as exc:
                raise CliError(str(exc)) from exc
            print(open_services(args.db).create_lab(lab_id, args.name))
            return 0
        if args.command == "fake-responses":
            return run_fake(args)
        if args.command == "backfill-outcomes":
            return run_backfill(args)
        if args.command == "dev-seed":
            count = dev_fake_count()
            fake = None
            if count:
                factory = store_factory(args.db)

                def fake(survey_id: str) -> str:
                    report = fake_responses(factory, survey_id, n=count)
                    return report.line()

            state, created = dev_seed(
                lambda: open_services(args.db), args.data_dir, args.fixture_dirs, fake=fake
            )
            print(
                dev_banner(
                    state,
                    created,
                    builder_url=args.builder_url.rstrip("/"),
                    api_url=args.api_url.rstrip("/"),
                    participant_link=args.participant_link or None,
                )
            )
            return 0
        out = seed_fixture(
            open_services(args.db),
            args.fixture_dir,
            user=args.user,
            lab=args.lab,
            save_mode=args.save_mode,
        )
    except (CliError, FakeError) as exc:
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
