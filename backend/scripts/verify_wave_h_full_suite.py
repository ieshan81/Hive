"""Wave H — full verification orchestrator."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

SUITES = [
    "verify_wave_a_suite.py",
    "verify_wave_c_d_suite.py",
    "verify_wave_e1_exit_only_suite.py",
    "verify_wave_e2_meme_spike_suite.py",
    "verify_wave_e3_candle_lab_suite.py",
    "verify_wave_f_strategy_import_suite.py",
    "verify_diagnostic_bundle_phase21.py",
]


def main():
    failed = []
    for name in SUITES:
        p = ROOT / "scripts" / name
        print(f"\n=== {name} ===")
        r = subprocess.run([PY, str(p)], cwd=str(ROOT))
        if r.returncode != 0:
            failed.append(name)
    if failed:
        print(f"\nFAILED: {failed}")
        sys.exit(1)
    print("\nALL_WAVE_H_SUITES_PASSED")


if __name__ == "__main__":
    main()
