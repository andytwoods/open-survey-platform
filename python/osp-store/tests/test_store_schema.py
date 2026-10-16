"""Schema: migrations match the metadata; no IP / network identifiers stored."""

from __future__ import annotations

import re

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from osp_store import downgrade, migrate
from osp_store import schema as t
from sqlalchemy import LargeBinary, inspect

EXPECTED_TABLES = {
    "tenants",
    "users",
    "surveys",
    "drafts",
    "op_log",
    "versions",
    "sessions",
    "responses",
    "audit_log",
    "themes",  # 0002_themes
    "lab_theme_defaults",
    # participant runtime (R2, migration 0003)
    "publications",
    "participant_sessions",
    "quota_counters",
    "quota_claims",
    "assignment_counters",
    "session_conflicts",
    "response_records",
    # builder accounts (C10, migration 0004_accounts)
    "user_mfa",
    "auth_sessions",
}

# Anything that would let us store where a participant connected from or with what.
FORBIDDEN = re.compile(
    r"(^|_)(ip|ips|ipv4|ipv6|ip_?addr(ess)?|remote_?addr(ess)?|client_?addr(ess)?|"
    r"host|hostname|user_?agent|ua|x_?forwarded(_for)?|forwarded_for|geo|geoip|"
    r"lat|lon|latitude|longitude|mac(_?addr)?)($|_)",
    re.IGNORECASE,
)


def test_migrated_schema_matches_metadata(engine):
    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"compare_type": True}), t.metadata
        )
    assert diff == []
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES | {"alembic_version"}


def test_downgrade_and_upgrade_again(engine):
    downgrade(engine)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    migrate(engine)
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_no_ip_address_or_network_identifier_columns(engine):
    """MVP 12b / review §9 Q8: no IP address and no user agent stored by default."""
    columns = [(tbl.name, c.name) for tbl in t.metadata.tables.values() for c in tbl.columns]
    insp = inspect(engine)
    columns += [
        (name, c["name"]) for name in insp.get_table_names() for c in insp.get_columns(name)
    ]
    offenders = [(tbl, col) for tbl, col in columns if FORBIDDEN.search(col)]
    assert offenders == []


def test_forbidden_pattern_catches_the_usual_names():
    for name in ("ip", "ip_address", "client_ip", "remote_addr", "user_agent", "ipv6", "geoip"):
        assert FORBIDDEN.search(name), name
    for name in ("tenant_id", "description", "submitted_at", "ship", "zip_code", "email"):
        assert not FORBIDDEN.search(name), name


def test_participant_fields_are_encrypted_columns():
    # Plaintext columns for participant data must not exist alongside the ciphertext.
    for table, ct, kid in t.ENCRYPTED_FIELDS:
        assert isinstance(table.c[ct].type, LargeBinary)
        assert kid in table.c
    assert "answers" not in t.responses.c and "instance" not in t.sessions.c
    assert "totp_secret" not in t.users.c
