"""Variable names a survey may not use, compared case-insensitively.

Why: response exports put our variable names next to columns the runtimes add themselves.
LimeSurvey renames a question code that clashes with a built-in column (e.g. `seed`) in its
JSON export and duplicates it in CSV (`spikes/spike-1/FINDINGS.md` Q2). Enketo/XForms adds
`meta/instanceID` and friends. Our own CSV export adds `<var>__state` companion columns
(semantics.md §1), and we keep a leading underscore for platform columns (`_order.*`).
"""

from __future__ import annotations

RESERVED_NAMES: frozenset[str] = frozenset(
    name.lower()
    for name in (
        # Ours / generic
        "id",
        "seed",
        "token",
        # LimeSurvey response table built-ins
        "submitdate",
        "lastpage",
        "startlanguage",
        "startdate",
        "datestamp",
        "ipaddr",
        "refurl",
        # ODK XForms / Enketo instance metadata (meta/instanceID ...)
        "instanceID",
        "instanceName",
        "deprecatedID",
        "meta",
    )
)

RESERVED_PREFIX = "_"
RESERVED_SUFFIX = "__state"


def reserved_reason(name: str) -> str | None:
    """Why `name` is reserved, or None if it is free to use."""
    if name.lower() in RESERVED_NAMES:
        return f"'{name}' is a column name used by a runtime or export"
    if name.startswith(RESERVED_PREFIX):
        return f"names starting with '{RESERVED_PREFIX}' are kept for platform columns"
    if name.lower().endswith(RESERVED_SUFFIX):
        return f"names ending in '{RESERVED_SUFFIX}' clash with CSV state columns"
    return None
