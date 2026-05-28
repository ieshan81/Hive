"""Verify Trader Console does not introduce a direct broker path."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> None:
    router = read("app/routers/cockpit.py")
    service = read("app/services/trader_console_service.py")
    main_py = read("app/main.py")
    allowlist = (ROOT.parent / "src/lib/operatorProxyAllowlist.ts").read_text(encoding="utf-8")

    assert 'APIRouter(prefix="/api"' in router
    assert "_op: str = Depends(require_operator_token)" in router
    assert '@router.post("/paper/manual-buy")' in router
    assert "manual_paper_buy(session, body, actor=actor)" in router
    assert "app.include_router(cockpit.router)" in main_py
    assert '"/api/paper/"' in allowlist

    assert "TrainingExecutionService(session).execute_approved_decision" in service
    assert "AggressivePaperLearningService(session)" in service
    assert "PaperExecutionService(" in service
    assert "submit_paper_order" not in service
    assert "submit_order" not in service
    assert "live_trading_locked" in service
    assert "is_paper_broker_url()" in service

    print("verify_trader_console_contract: PASS")


if __name__ == "__main__":
    main()
