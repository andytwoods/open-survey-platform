"""``osp-cli fake-responses`` (task DS1, dev only): fill a published survey with invented,
realistic responses so the Results page can be tried without answering it by hand.

Each fake participant is genuine as far as the server can tell:

- the session is started by the participant ``SessionService`` (``osp_runtime``) over the
  store, the path ``POST /api/s/{slug}/sessions`` takes, so the session seed, simple and
  balanced assignment and quota places are the server's own;
- the participant is played through the real TypeScript engine
  (``web/engine-sim/dist/fake.js``, ``make sim-build``), which produces the event log,
  snapshots, randomiser orders, question states and the ``ResponseRecord`` exactly as the
  participant app does;
- consent, snapshot saves, quota checks and the submit go through the same service calls
  as the participant endpoints, so the record is validated as a real one is.

Times are spread over ``--days`` before now (more early on, fewer later; mostly daytime)
by running the service and the store on a clock that is set to each participant's engine
time. A share ``--partial`` drops out part-way: their last snapshot is saved and they
never submit. The run is deterministic for a ``--seed`` (session seeds come from a
seeded generator; resume tokens stay random).

Refused unless ``OSP_ENV=dev``: this writes invented data into the database.
"""

from __future__ import annotations

import json
import math
import os
import random
import secrets
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from osp_app.identity import DEV_LAB_ID
from osp_app.runtime_repo import SYSTEM, StoreParticipantRepo
from osp_runtime import SessionService
from osp_store import Store, TenantContext

FAKE_CLI = Path(__file__).resolve().parents[4] / "web" / "engine-sim" / "dist" / "fake.js"
MAX_N = 5000
MAX_DAYS = 366


class FakeError(Exception):
    """A user-facing failure of the fake-response run."""


def require_dev(environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    if (env.get("OSP_ENV") or "").strip().lower() != "dev":
        raise FakeError("fake-responses is for local development only: set OSP_ENV=dev")


class FakeClock:
    """The time the service and store see: set to each fake participant's engine time."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def now(self) -> datetime:
        return self.at

    def set_ms(self, ms: float) -> None:
        self.at = datetime.fromtimestamp(ms / 1000, UTC)


class SeededSeeds:
    """``RandomSource`` with seeded session seeds (so a ``--seed`` reproduces assignments
    and randomiser orders) and real random resume tokens."""

    def __init__(self, seed: str) -> None:
        self._r = random.Random(f"osp-fake-sessions:{seed}")

    def randbelow(self, n: int) -> int:
        return self._r.randrange(n)

    def token_bytes(self, n: int) -> bytes:
        return secrets.token_bytes(n)


class _NoLimit:
    """Fake participants arrive in a burst; the API's start limiter would refuse them."""

    def allow(self, key: str, cost: float = 1.0) -> bool:
        return True


class _Node:
    """The fake-participant driver: JSON lines over a pipe."""

    def __init__(self, cli: Path | None, node: str | None) -> None:
        node_bin = node or os.environ.get("OSP_NODE") or shutil.which("node")
        path = cli or Path(os.environ.get("OSP_FAKE_CLI") or FAKE_CLI)
        if not node_bin:
            raise FakeError("node is not installed")
        if not path.is_file():
            raise FakeError(f"{path} is not built: run `make sim-build`")
        self.proc = subprocess.Popen(
            [node_bin, path.as_posix()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )

    def send(self, body: object) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(body, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def recv(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            raise FakeError("the fake-participant driver stopped unexpectedly")
        msg = json.loads(line)
        if "error" in msg:
            err = msg["error"]
            raise FakeError(f"engine: {err.get('code')}: {err.get('message')}")
        return msg

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 - best effort
            self.proc.kill()


def arrivals(rnd: random.Random, n: int, days: float, now: datetime) -> list[datetime]:
    """Session start times over the ``days`` before ``now``: a launch peak decaying over
    the window, mostly in the daytime and early evening, none in the last hour."""
    launch = now - timedelta(days=days)
    latest = now - timedelta(hours=1)
    out: list[datetime] = []
    whole = max(1, math.ceil(days))
    weights = [math.exp(-d / max(1.0, days / 3)) + 0.12 for d in range(whole)]
    while len(out) < n:
        day = rnd.choices(range(whole), weights)[0]
        hour = rnd.gauss(13, 3) if rnd.random() < 0.62 else rnd.gauss(20.5, 1.5)
        hour = min(23.95, max(6.5, hour))
        midnight = (launch + timedelta(days=day)).replace(hour=0, minute=0, second=0)
        at = midnight + timedelta(hours=hour, seconds=rnd.randrange(60))
        if launch <= at <= latest:
            out.append(at.replace(microsecond=0))
    return sorted(out)


@dataclass
class FakeReport:
    slug: str
    survey_id: str | None
    plan_checksum: str
    n: int
    submitted: int = 0
    dropped: int = 0
    stuck: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    first: str | None = None
    last: str | None = None
    participants: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "surveyId": self.survey_id,
            "planChecksum": self.plan_checksum,
            "sessions": self.n,
            "submitted": self.submitted,
            "droppedOut": self.dropped,
            "stuck": self.stuck,
            "outcomes": dict(sorted(self.outcomes.items())),
            "from": self.first,
            "to": self.last,
        }

    def line(self) -> str:
        ends = ", ".join(f"{k} {v}" for k, v in sorted(self.outcomes.items()))
        stuck = f", {self.stuck} stuck" if self.stuck else ""
        return (
            f"{self.n} fake sessions: {self.submitted} submitted ({ends or 'none'}), "
            f"{self.dropped} dropped out{stuck}"
        )


def _publication(repo: StoreParticipantRepo, store: Store, target: str, lab: str) -> Any:
    pub = repo.ps.find_publication(SYSTEM, target)
    if pub is not None:
        return pub, None
    try:
        survey = store.get_survey(TenantContext(lab, "system:fake-responses"), target)
    except Exception as exc:  # noqa: BLE001 - not found, or not an id at all
        raise FakeError(f"no published survey with id or slug {target!r} in {lab}") from exc
    pub = repo.ps.find_publication(SYSTEM, survey.public_slug) if survey.public_slug else None
    if pub is None:
        raise FakeError(f"survey {target!r} has not been published")
    return pub, survey.id


def fake_responses(
    store_factory: Callable[[Callable[[], datetime]], Store],
    target: str,
    *,
    n: int = 150,
    seed: int = 1,
    partial: float = 0.15,
    days: float = 21,
    lab: str = DEV_LAB_ID,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
    cli: Path | None = None,
    node: str | None = None,
    keep_participants: bool = False,
) -> FakeReport:
    """Create ``n`` fake sessions on the latest published version of ``target`` (a survey
    id in ``lab`` or a public slug). ``store_factory(clock)`` opens the store on a clock."""
    require_dev(environ)
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_N:
        raise FakeError(f"--n must be an integer from 1 to {MAX_N}")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
        raise FakeError("--seed must be an integer from 0 to 2^31 - 1")
    if not 0 <= partial <= 1:
        raise FakeError("--partial must be a share from 0 to 1")
    if not 0 < days <= MAX_DAYS:
        raise FakeError(f"--days must be more than 0 and at most {MAX_DAYS}")
    end = (now or datetime.now(UTC)).astimezone(UTC)
    clock = FakeClock(end)
    store = store_factory(clock)
    repo = StoreParticipantRepo(store)
    pub, survey_id = _publication(repo, store, target, lab)
    plan = pub.plan
    if isinstance(plan, Mapping) and plan.get("hooks"):
        raise FakeError("surveys with researcher hooks can't be filled with fake responses")
    sessions = SessionService(
        repo,
        clock=clock,
        rng=SeededSeeds(f"{seed}:{pub.plan_checksum}"),
        start_limiter=_NoLimit(),  # type: ignore[arg-type]
    )
    # Per survey too, so surveys filled with one seed don't mirror each other.
    rnd = random.Random(f"osp-fake-run:{seed}:{pub.plan_checksum}")
    times = arrivals(rnd, n, days, end)
    drops = [rnd.random() if rnd.random() < partial else None for _ in range(n)]
    report = FakeReport(pub.slug, survey_id, pub.plan_checksum, n)
    driver = _Node(cli, node)
    try:
        driver.send({"op": "init", "plan": plan, "seed": rnd.randrange(2**31)})
        driver.recv()
        for i, (at, drop) in enumerate(zip(times, drops, strict=True)):
            clock.at = at
            st = sessions.start(pub.slug)
            outcome = _play(driver, sessions, clock, st, i, at, drop)
            if outcome["submitted"]:
                report.submitted += 1
                key = str(outcome["end"] or "(none)")
                report.outcomes[key] = report.outcomes.get(key, 0) + 1
            elif outcome["stuck"]:
                report.stuck += 1
            else:
                report.dropped += 1
            if keep_participants:
                report.participants.append({"sessionId": st.session_id, "dropAt": drop, **outcome})
    finally:
        driver.close()
    # What the server's release job does: drop-outs idle for 24 h give their places back.
    clock.at = end
    sessions.release_inactive()
    report.first = times[0].isoformat() if times else None
    report.last = times[-1].isoformat() if times else None
    return report


def _play(
    driver: _Node,
    sessions: SessionService,
    clock: FakeClock,
    st: Any,
    index: int,
    at: datetime,
    drop: float | None,
) -> dict[str, Any]:
    token, sid, revision = st.resume_token, st.session_id, st.revision
    driver.send(
        {
            "op": "run",
            "spec": {
                "index": index,
                "sessionSeed": st.session_seed,
                "assigned": st.assigned,
                "sessionId": sid,
                "startMs": int(at.timestamp() * 1000),
                "dropAt": drop,
                "saveMode": st.save_mode,
            },
        }
    )
    while True:
        msg = driver.recv()
        if "done" in msg:
            return msg["done"]
        ask = msg["ask"]
        clock.set_ms(ask["at"])
        reply: dict[str, Any] = {}
        match ask["do"]:
            case "consent":
                sessions.consent(sid, token, ask["version"])
            case "save":
                revision = sessions.save_snapshot(sid, token, revision, ask["snapshot"]).revision
            case "quota":
                reply["result"] = sessions.check_quota(sid, token, ask["node"]).result
            case "submit":
                sessions.submit(sid, token, ask["record"])
            case other:
                raise FakeError(f"unknown request from the driver: {other!r}")
        driver.send({"reply": reply})
