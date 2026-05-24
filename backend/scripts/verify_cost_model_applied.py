import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.services.research_cost_model import round_trip_cost_pct, apply_trade_return


def main():
    cm = round_trip_cost_pct("DOGE/USD", DEFAULT_CONFIG)
    assert cm["round_trip_pct"] > 0
    net = apply_trade_return(0.01, "DOGE/USD", DEFAULT_CONFIG)
    assert net < 0.01
    print("verify_cost_model_applied: OK", cm["round_trip_pct"])


if __name__ == "__main__":
    main()
