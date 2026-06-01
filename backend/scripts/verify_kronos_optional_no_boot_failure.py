"""Kronos is optional: app/Alpha Factory work when the dependency/model is missing."""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.kronos_market_model_service import KronosMarketModelService, kronos_config


def test_disabled_by_default_no_crash() -> None:
    svc = KronosMarketModelService()
    assert svc.is_available() is False, "Kronos must be unavailable by default (disabled / dep missing)"
    fc = svc.forecast_symbol("ETH/USD", "5Min", [{"o": 1, "h": 2, "l": 1, "c": 2, "v": 10}])
    assert fc["available"] is False and fc["forecast_direction"] == "unavailable", fc
    assert "error" not in fc or fc.get("error_if_unavailable") is not None or fc["reason"], fc
    print("kronos: disabled by default -> available=false, forecast unavailable, no crash — PASS")


def test_config_defaults_capped() -> None:
    cfg = kronos_config()
    assert cfg["enabled"] is False, cfg
    assert cfg["model_size"] in ("mini", "small", "base"), cfg
    assert 0.0 <= cfg["weight_in_alpha_score"] <= 0.25, cfg
    print("kronos: config OFF by default; weight capped <= 0.25 — PASS")


def test_alpha_factory_imports_without_kronos() -> None:
    # Alpha Factory must not depend on Kronos for import/boot.
    assert importlib.util.find_spec("app.services.autonomous_alpha_factory_service") is not None
    import app.services.autonomous_alpha_factory_service as af  # noqa: F401

    print("kronos: Alpha Factory service imports without Kronos — PASS")


if __name__ == "__main__":
    test_disabled_by_default_no_crash()
    test_config_defaults_capped()
    test_alpha_factory_imports_without_kronos()
    print("ALL PASS: verify_kronos_optional_no_boot_failure")
