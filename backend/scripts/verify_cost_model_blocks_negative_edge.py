from _alpha_factory_verify_common import session_with_config

from app.services.cost_model_service import CostModelService


def main() -> None:
    session, cfg = session_with_config()
    out = CostModelService(session, cfg).estimate("BTC/USD", expected_move_pct=0.0001, spread_pct=0.002)
    assert out["status"] == "blocked", out
    assert out["edge_after_cost_bps"] < 0, out
    print("verify_cost_model_blocks_negative_edge: PASS")
    print(out)


if __name__ == "__main__":
    main()
