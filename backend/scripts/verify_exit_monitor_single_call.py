"""Fast training phases must not call monitor_exits twice for exit-only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

src = (Path(__file__).resolve().parents[1] / "app/services/fast_crypto_training_loop.py").read_text(
    encoding="utf-8"
)
# Duplicate exit-only monitor_exits block removed
assert src.count("exit_only_monitor_exits") == 0 or "exit_only_monitor_exits" not in src
assert "monitor_exits()" in src
print("ALL_CHECKS_PASSED")
