import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG


def main():
    assert DEFAULT_CONFIG["research"]["auto_backtest_enabled"] is False
    print("verify_auto_backtest_disabled_by_default: OK")


if __name__ == "__main__":
    main()
