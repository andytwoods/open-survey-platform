#!/usr/bin/env python3
"""Licence gate for Python and JS dependencies (policy: /licence-policy.toml).

Run via `make licence-check` (part of `make check`):

    uv run python scripts/licence_check.py

Python deps come from the active uv venv (importlib.metadata). A dependency counts
as *runtime* if it is reachable from a workspace package's own requirements;
everything else (dev groups, tooling) counts as *dev*. JS deps come from
`pnpm -r licenses list`; anything not in the `--prod` listing counts as *dev*.

`--extra FILE` adds synthetic dependencies (JSON list) so tests can prove that a
GPL dependency fails the gate without adding GPL code to the tree.

Exit codes: 0 ok, 1 policy violations, 2 could not collect dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO / "licence-policy.toml"


@dataclass(frozen=True)
class Dep:
    ecosystem: str  # "python" | "js"
    name: str
    version: str
    licence: str | None  # raw licence string / SPDX expression, None if unknown
    dev: bool


@dataclass(frozen=True)
class Verdict:
    dep: Dep
    spdx: str | None
    ok: bool
    reason: str


# --- Normalisation ---------------------------------------------------------------

_ALIASES = {
    "mit": "MIT",
    "mit license": "MIT",
    "the mit license": "MIT",
    "the mit license (mit)": "MIT",
    "expat": "MIT",
    "mit no attribution license (mit-0)": "MIT-0",
    "bsd": "BSD-3-Clause",
    "bsd license": "BSD-3-Clause",
    "new bsd": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "modified bsd": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "bsd 3-clause license": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",
    "bsd-3": "BSD-3-Clause",
    "simplified bsd": "BSD-2-Clause",
    "bsd 2-clause": "BSD-2-Clause",
    "bsd 2-clause license": "BSD-2-Clause",
    "bsd-2": "BSD-2-Clause",
    "zero-clause bsd (0bsd)": "0BSD",
    "apache": "Apache-2.0",
    "apache 2": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache-2": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "apache software license 2.0": "Apache-2.0",
    "isc license": "ISC",
    "isc license (iscl)": "ISC",
    "python software foundation license": "PSF-2.0",
    "psf": "PSF-2.0",
    "psf license": "PSF-2.0",
    "the unlicense (unlicense)": "Unlicense",
    "cc0 1.0 universal (cc0 1.0) public domain dedication": "CC0-1.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "blue oak model license 1.0.0": "BlueOak-1.0.0",
}

# Copyleft families detected by words, so classifiers we have no alias for still fail
# with a clear reason instead of "unknown".
_COPYLEFT_WORDS = [
    ("affero", "AGPL-3.0-or-later"),
    ("lesser general public", "LGPL-3.0-or-later"),
    ("library general public", "LGPL-2.0-or-later"),
    ("general public license", "GPL-3.0-or-later"),
    ("server side public", "SSPL-1.0"),
    ("business source", "BUSL-1.1"),
]


def normalise(raw: str | None) -> str | None:
    """Map a licence string to an SPDX expression, or None if unidentifiable."""
    if raw is None:
        return None
    text = raw.strip()
    if not text or "\n" in text or len(text) > 120:
        return None  # empty, or a pasted licence text
    alias = _ALIASES.get(text.lower())
    if alias:
        return alias
    low = text.lower()
    for word, spdx in _COPYLEFT_WORDS:
        if word in low:
            return spdx
    if low.startswith("see licen"):
        return None
    # Looks like an SPDX expression already ("MIT", "(MIT OR Apache-2.0)", ...).
    if re.fullmatch(r"[A-Za-z0-9.+\-() ]+", text):
        return text
    return None


def classifier_expression(classifiers: list[str]) -> str | None:
    """Join licence classifiers as alternatives (packages list each option they offer)."""
    ids = []
    for c in classifiers:
        parts = [p.strip() for p in c.split("::")]
        if parts[0] != "License" or parts[-1] in ("OSI Approved", "License"):
            continue
        spdx = normalise(parts[-1])
        if spdx is None:
            return None
        ids.append(spdx)
    if not ids:
        return None
    return " OR ".join(f"({i})" if " " in i else i for i in dict.fromkeys(ids))


# --- SPDX expression evaluation --------------------------------------------------


class _Parser:
    def __init__(self, expr: str):
        self.tokens = re.findall(r"\(|\)|[^\s()]+", expr)
        self.i = 0

    def peek(self) -> str | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> str:
        tok = self.peek()
        if tok is None:
            raise ValueError("unexpected end of expression")
        self.i += 1
        return tok

    def parse(self) -> tuple:
        node = self.or_expr()
        if self.peek() is not None:
            raise ValueError(f"unexpected token {self.peek()!r}")
        return node

    def or_expr(self) -> tuple:
        nodes = [self.and_expr()]
        while (self.peek() or "").upper() == "OR":
            self.take()
            nodes.append(self.and_expr())
        return ("or", nodes) if len(nodes) > 1 else nodes[0]

    def and_expr(self) -> tuple:
        nodes = [self.atom()]
        while (self.peek() or "").upper() == "AND":
            self.take()
            nodes.append(self.atom())
        return ("and", nodes) if len(nodes) > 1 else nodes[0]

    def atom(self) -> tuple:
        tok = self.take()
        if tok == "(":
            node = self.or_expr()
            if self.take() != ")":
                raise ValueError("missing )")
            return node
        if tok in (")",) or tok.upper() in ("AND", "OR", "WITH"):
            raise ValueError(f"unexpected token {tok!r}")
        if (self.peek() or "").upper() == "WITH":  # "X WITH exception": judge X
            self.take()
            self.take()
        return ("id", tok.rstrip("+"))


def satisfiable(expr: str, allowed: set[str]) -> bool:
    """True if the expression can be satisfied using only `allowed` licence ids."""

    def ev(node: tuple) -> bool:
        kind, val = node
        if kind == "id":
            return val in allowed
        results = [ev(n) for n in val]
        return any(results) if kind == "or" else all(results)

    return ev(_Parser(expr).parse())


# --- Policy ----------------------------------------------------------------------


def load_policy(path: Path = POLICY_PATH) -> dict:
    return tomllib.loads(path.read_text())


def judge(dep: Dep, policy: dict) -> Verdict:
    overrides = {(o["ecosystem"], o["name"]): o for o in policy.get("override", [])}
    override = overrides.get((dep.ecosystem, dep.name))
    raw = override["licence"] if override else dep.licence
    spdx = normalise(raw)
    if spdx is None:
        return Verdict(dep, None, False, f"unknown licence {raw!r}: add an [[override]]")
    allowed = set(policy["allowed"])
    dev_only = set(policy.get("dev_only", []))
    try:
        if satisfiable(spdx, allowed):
            return Verdict(dep, spdx, True, "allowed")
        if satisfiable(spdx, allowed | dev_only):
            if dep.dev:
                return Verdict(dep, spdx, True, "dev-only licence, dev dependency")
            exceptions = {(e["ecosystem"], e["name"]) for e in policy.get("runtime_exception", [])}
            if (dep.ecosystem, dep.name) in exceptions:
                return Verdict(dep, spdx, True, "runtime exception (policy)")
            return Verdict(dep, spdx, False, f"{spdx} is allowed for dev/test deps only")
    except ValueError as exc:
        return Verdict(dep, spdx, False, f"unparseable licence expression {spdx!r}: {exc}")
    denied = [p for p in policy.get("denied_prefixes", []) if p.lower() in spdx.lower()]
    why = "denied licence" if denied else "licence not on the allowlist"
    return Verdict(dep, spdx, False, f"{why}: {spdx}")


# --- Collection ------------------------------------------------------------------


def _canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?")


def _requirements(dist: metadata.Distribution, extras: set[str]) -> list[tuple[str, set[str]]]:
    out = []
    for req in dist.requires or []:
        spec, _, marker = req.partition(";")
        m = _REQ.match(spec)
        if not m:
            continue
        wanted = re.findall(r"extra\s*==\s*['\"]([^'\"]+)['\"]", marker)
        if wanted and not (set(map(_canon, wanted)) & extras):
            continue  # belongs to an extra nobody asked for
        sub_extras = {_canon(e) for e in (m.group(2) or "").split(",") if e.strip()}
        out.append((_canon(m.group(1)), sub_extras))
    return out


def python_deps() -> list[Dep]:
    dists = {_canon(d.metadata["Name"]): d for d in metadata.distributions()}
    workspace = {
        _canon(tomllib.loads(p.read_text())["project"]["name"])
        for p in (REPO / "python").glob("*/pyproject.toml")
    }
    missing = workspace - dists.keys()
    if missing:
        raise RuntimeError(f"workspace packages not installed (run `uv sync`): {sorted(missing)}")
    runtime: set[str] = set()
    queue = [(name, set()) for name in workspace]
    seen: set[tuple[str, frozenset[str]]] = set()
    while queue:
        name, extras = queue.pop()
        key = (name, frozenset(extras))
        if key in seen or name not in dists:
            continue
        seen.add(key)
        runtime.add(name)
        queue.extend(_requirements(dists[name], extras))

    deps = []
    for name, dist in sorted(dists.items()):
        md = dist.metadata
        lic = md.get("License-Expression")
        if not lic:
            lic = classifier_expression(
                [c for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
            )
        if not lic:
            lic = md.get("License")
        deps.append(Dep("python", name, dist.version, lic, dev=name not in runtime))
    return deps


def _pnpm_licences(web: Path, prod: bool) -> dict:
    cmd = ["pnpm", "-C", str(web), "-r", "licenses", "list", "--json"]
    if prod:
        cmd.append("--prod")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{result.stderr or result.stdout}")
    return json.loads(result.stdout or "{}")


def js_deps(web: Path = REPO / "web") -> list[Dep]:
    def flatten(listing: dict) -> dict[tuple[str, str], str]:
        out = {}
        for group_licence, pkgs in listing.items():
            for pkg in pkgs:
                for version in pkg["versions"]:
                    out[(pkg["name"], version)] = pkg.get("license") or group_licence
        return out

    everything = flatten(_pnpm_licences(web, prod=False))
    prod = flatten(_pnpm_licences(web, prod=True))
    return [
        Dep("js", name, version, lic, dev=(name, version) not in prod)
        for (name, version), lic in sorted(everything.items())
    ]


def load_extra(path: Path) -> list[Dep]:
    return [
        Dep(e["ecosystem"], e["name"], e.get("version", "0"), e.get("licence"), e.get("dev", False))
        for e in json.loads(path.read_text())
    ]


# --- CLI -------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-python", action="store_true", help="skip Python dependencies")
    ap.add_argument("--no-js", action="store_true", help="skip JS dependencies")
    ap.add_argument("--extra", type=Path, help="JSON list of extra deps to judge (tests)")
    ap.add_argument("--policy", type=Path, default=POLICY_PATH)
    ap.add_argument("-v", "--verbose", action="store_true", help="list every dependency")
    args = ap.parse_args(argv)

    policy = load_policy(args.policy)
    deps: list[Dep] = []
    try:
        if not args.no_python:
            deps += python_deps()
        if not args.no_js:
            deps += js_deps()
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"licence check: could not collect dependencies: {exc}", file=sys.stderr)
        return 2
    if args.extra:
        deps += load_extra(args.extra)

    verdicts = [judge(d, policy) for d in deps]
    bad = [v for v in verdicts if not v.ok]
    dev_only = [v for v in verdicts if v.ok and v.reason.startswith("dev-only")]
    if args.verbose:
        for v in verdicts:
            kind = "dev" if v.dep.dev else "run"
            print(f"  {v.dep.ecosystem:6} {kind} {v.dep.name}@{v.dep.version}: {v.spdx}")
    for v in bad:
        kind = "dev" if v.dep.dev else "runtime"
        print(
            f"LICENCE FAIL [{v.dep.ecosystem} {kind}] {v.dep.name}@{v.dep.version}: {v.reason}",
            file=sys.stderr,
        )
    counts = {eco: sum(d.ecosystem == eco for d in deps) for eco in ("python", "js")}
    note = ", ".join(sorted({f"{v.dep.name} ({v.spdx})" for v in dev_only}))
    print(
        f"licence check: {len(deps)} deps (python {counts['python']}, js {counts['js']}), "
        f"{len(bad)} violations" + (f"; dev-only licences: {note}" if note else "")
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
