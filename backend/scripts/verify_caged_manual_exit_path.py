from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> None:
    api = read("app/routers/api.py")
    training = read("app/services/training_execution_service.py")
    paper = read("app/services/paper_execution_service.py")
    closing = read("app/services/closing_position_preflight.py")
    eligibility = read("app/services/account_pair_eligibility_service.py")

    assert '@router.post("/positions/{symbol}/manual-exit-request")' in api
    assert "_op: str = Depends(require_operator_token)" in api
    assert "TrainingExecutionService(session).request_manual_exit(symbol, actor=actor)" in api
    assert "def request_manual_exit" in training
    assert "operator_requested=True" in training
    assert "TrainingExecutionService" in training and "PaperExecutionService" in training
    assert "preflight_side = cand.side" in paper
    assert '"manual_operator_exit"' in closing
    assert 'if side.lower() != "buy":' in eligibility

    print("verify_caged_manual_exit_path: PASS")


if __name__ == "__main__":
    main()
