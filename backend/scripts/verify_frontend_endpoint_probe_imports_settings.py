"""Frontend endpoint probe must import settings correctly (no get_settings ImportError).

Regression guard for: `cannot import name 'get_settings' from app.config`.
app.config exposes a module-level `settings` (Settings instance), not get_settings().
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_config_exposes_settings_not_get_settings() -> None:
    import app.config as cfg

    assert hasattr(cfg, "settings"), "app.config must expose a module-level `settings`"
    assert hasattr(cfg.settings, "api_host") and hasattr(cfg.settings, "api_port"), "settings missing api_host/api_port"
    assert not hasattr(cfg, "get_settings"), "app.config has no get_settings — probe must not import it"
    print("frontend-probe: app.config.settings present; get_settings absent — PASS")


def test_probe_runs_without_import_error() -> None:
    # The bug was an ImportError at call time. The probe must import + run and return a list;
    # individual endpoint probes may degrade, but the function itself must not raise.
    from app.services.frontend_api_contract import build_frontend_endpoint_status

    session = _mem()
    rows = build_frontend_endpoint_status(session)
    assert isinstance(rows, list), type(rows)
    session.close()
    print(f"frontend-probe: build_frontend_endpoint_status() ran, {len(rows)} probe rows, no ImportError — PASS")


if __name__ == "__main__":
    test_config_exposes_settings_not_get_settings()
    test_probe_runs_without_import_error()
    print("ALL PASS: verify_frontend_endpoint_probe_imports_settings")
