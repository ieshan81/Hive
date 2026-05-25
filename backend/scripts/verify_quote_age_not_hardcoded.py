"""Quote age is not always hardcoded to zero."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Inspect source — paper_execution must not assign quote_age_seconds = 0 unconditionally
src = (Path(__file__).resolve().parents[1] / "app/services/paper_execution_service.py").read_text(
    encoding="utf-8"
)
assert 'quote["quote_age_seconds"] = 0' not in src
assert "quote_age_unknown" in src or "quote_age_status" in src
print("ALL_CHECKS_PASSED")
