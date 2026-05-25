"""Worker refuses without HIVE_WORKER_EXPLICIT_ENABLE."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = {**__import__("os").environ}
    env.pop("HIVE_WORKER_EXPLICIT_ENABLE", None)
    r = subprocess.run(
        [sys.executable, str(ROOT / "worker.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert r.returncode != 0
    assert "HIVE_WORKER_EXPLICIT_ENABLE" in (r.stderr or "") + (r.stdout or "")
    with open(ROOT / "Procfile") as f:
        content = f.read()
    assert "worker:" not in content.lower() or "worker" not in content
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
