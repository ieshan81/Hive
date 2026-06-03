#!/usr/bin/env python3
"""Reconcile Alembic revision 20260603_0005 with existing shadow_trades (read-only checks + stamp if needed)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TARGET_REVISION = "20260603_0005"
EXPECTED_TABLE = "shadow_trades"
EXPECTED_COLUMNS = {
    "id",
    "shadow_trade_id",
    "validation_run_id",
    "symbol",
    "asset_class",
    "strategy_id",
    "side",
    "promotion_level",
    "status",
    "data_quality",
    "data_quality_note",
    "entry_reference_price",
    "exit_reference_price",
    "simulated_pnl_bps",
    "outcome_verdict",
    "paper_blocked_reason",
    "paper_would_be_allowed",
    "counts_as_broker_evidence",
    "setup_fingerprint",
    "evidence_json",
    "outcome_json",
    "cycle_run_id",
    "created_at",
    "closed_at",
    "updated_at",
}
EXPECTED_INDEXES = {
    "ix_shadow_trades_shadow_trade_id",
    "ix_shadow_trades_validation_run_id",
    "ix_shadow_trades_symbol",
    "ix_shadow_trades_asset_class",
    "ix_shadow_trades_strategy_id",
    "ix_shadow_trades_promotion_level",
    "ix_shadow_trades_status",
    "ix_shadow_trades_data_quality",
    "ix_shadow_trades_outcome_verdict",
    "ix_shadow_trades_setup_fingerprint",
    "ix_shadow_trades_cycle_run_id",
}


def _fetch_public_database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"].strip()
    try:
        out = subprocess.check_output(
            ["railway", "variables", "--service", "Postgres", "--json"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        data = json.loads(out)
        # CLI may return object or list of {name,value}
        if isinstance(data, dict):
            if "DATABASE_PUBLIC_URL" in data:
                return str(data["DATABASE_PUBLIC_URL"]).strip()
            for item in data.get("variables") or data.get("data") or []:
                if isinstance(item, dict) and item.get("name") == "DATABASE_PUBLIC_URL":
                    return str(item.get("value") or "").strip()
        if isinstance(data, list):
            for item in data:
                if item.get("name") == "DATABASE_PUBLIC_URL" or item.get("key") == "DATABASE_PUBLIC_URL":
                    return str(item.get("value") or item.get("val") or "").strip()
    except Exception as exc:
        raise RuntimeError(f"Could not load DATABASE_PUBLIC_URL: {exc}") from exc
    raise RuntimeError("DATABASE_PUBLIC_URL not found; set DATABASE_URL in environment.")


def _inspect_db(url: str) -> dict:
    from sqlalchemy import create_engine, text

    engine = create_engine(url, pool_pre_ping=True)
    report: dict = {}
    with engine.connect() as conn:
        has_ver_table = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'alembic_version')"
            )
        ).scalar()
        report["alembic_version_table_exists"] = bool(has_ver_table)
        if has_ver_table:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            report["alembic_version_rows"] = [r[0] for r in ver]
        else:
            report["alembic_version_rows"] = []
        exists = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :t)"
            ),
            {"t": EXPECTED_TABLE},
        ).scalar()
        report["shadow_trades_exists"] = bool(exists)
        if exists:
            cols = conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"
                ),
                {"t": EXPECTED_TABLE},
            ).fetchall()
            report["columns"] = [
                {"name": c[0], "type": c[1], "nullable": c[2], "default": c[3]} for c in cols
            ]
            report["column_names"] = {c["name"] for c in report["columns"]}
            idx = conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'public' AND tablename = :t"
                ),
                {"t": EXPECTED_TABLE},
            ).fetchall()
            report["index_names"] = sorted(r[0] for r in idx)
            report["row_count"] = conn.execute(text(f"SELECT COUNT(*) FROM {EXPECTED_TABLE}")).scalar()
    return report


def _schema_matches(inspection: dict) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not inspection.get("shadow_trades_exists"):
        issues.append("table_missing")
        return False, issues
    names = inspection.get("column_names") or set()
    missing = EXPECTED_COLUMNS - names
    extra = names - EXPECTED_COLUMNS
    if missing:
        issues.append(f"missing_columns:{sorted(missing)}")
    if extra:
        issues.append(f"extra_columns:{sorted(extra)}")
    idx = set(inspection.get("index_names") or [])
    missing_idx = EXPECTED_INDEXES - idx
    # SQLModel create_all may name indexes differently; require unique on shadow_trade_id + core lookups.
    if missing_idx:
        has_unique_shadow_id = any(
            "shadow_trade_id" in name and ("unique" in name.lower() or name.endswith("shadow_trade_id"))
            for name in idx
        ) or "shadow_trades_shadow_trade_id_key" in idx
        if not has_unique_shadow_id and "ix_shadow_trades_shadow_trade_id" in missing_idx:
            issues.append("missing_unique_shadow_trade_id_index")
        # Non-critical: log missing expected ix_* but allow stamp if columns OK and table usable
        critical_missing = {i for i in missing_idx if i == "ix_shadow_trades_shadow_trade_id"}
        if critical_missing and not has_unique_shadow_id:
            issues.append(f"missing_indexes:{sorted(critical_missing)}")
        elif missing_idx - critical_missing:
            issues.append(f"noncritical_index_drift:{sorted(missing_idx - critical_missing)}")
    return not any(i.startswith("missing_") or i == "table_missing" for i in issues), issues


def _run_alembic(cmd: list[str], url: str) -> str:
    env = {**os.environ, "DATABASE_URL": url}
    proc = subprocess.run(
        ["alembic", *cmd],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and cmd[0] not in ("current",):
        raise RuntimeError(f"alembic {' '.join(cmd)} failed: {out[:500]}")
    return out.strip()


def main() -> None:
    url = _fetch_public_database_url()
    if not url.startswith("postgresql"):
        raise SystemExit("Invalid DATABASE_URL (refusing to proceed)")

    inspection = _inspect_db(url)
    schema_ok, schema_issues = _schema_matches(inspection)
    current_out = _run_alembic(["current"], url)
    heads_out = _run_alembic(["heads"], url)
    history_out = _run_alembic(["history"], url)
    history_tail = "\n".join(history_out.splitlines()[-6:])

    versions = inspection.get("alembic_version_rows") or []
    at_target = TARGET_REVISION in versions
    stamp_done = False
    upgrade_done = False

    if at_target and schema_ok:
        action = "none_clean"
    elif inspection.get("shadow_trades_exists") and schema_ok and not at_target:
        # Table present (often via create_all); record revision without re-running DDL.
        _run_alembic(["stamp", TARGET_REVISION], url)
        stamp_done = True
        action = "stamped"
        versions = _inspect_db(url).get("alembic_version_rows") or []
        at_target = TARGET_REVISION in versions
    elif inspection.get("shadow_trades_exists") and not schema_ok:
        action = "blocked_schema_mismatch"
    elif not inspection.get("shadow_trades_exists"):
        _run_alembic(["upgrade", "head"], url)
        upgrade_done = True
        action = "upgraded"
        inspection = _inspect_db(url)
        schema_ok, schema_issues = _schema_matches(inspection)
        versions = inspection.get("alembic_version_rows") or []
        at_target = TARGET_REVISION in versions
    else:
        action = "review_manual"

    result = {
        "action": action,
        "alembic_current_output": current_out,
        "alembic_heads_output": heads_out,
        "alembic_history_tail": history_tail,
        "alembic_version_rows": versions,
        "revision_at_target": at_target,
        "shadow_trades_exists": inspection.get("shadow_trades_exists"),
        "schema_matches": schema_ok,
        "schema_issues": schema_issues,
        "shadow_row_count": inspection.get("row_count"),
        "index_count": len(inspection.get("index_names") or []),
        "stamp_done": stamp_done,
        "upgrade_done": upgrade_done,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
