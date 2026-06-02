"""Verify no Alpaca/operator secret has leaked into git-tracked files, and .env is untracked.

Checks (never prints any secret value or matching line):
  1. backend/.env is NOT tracked by git.
  2. The live secret VALUES (alpaca key/secret, operator token) do not appear in any tracked text file.
  3. .env.example files (if present) contain placeholders only — no real-looking long secret values.

Read-only. Exits non-zero with a generic reason on any leak (the offending value is never echoed).
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.config import settings  # noqa: E402


def _tracked_files() -> list[str]:
    r = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def main() -> None:
    tracked = _tracked_files()

    # 1) .env must not be tracked
    leaked_env = [f for f in tracked if f.endswith(".env") or f.endswith("/.env")]
    assert not leaked_env, f".env file(s) are tracked by git: {leaked_env}"

    # 2) live secret values must not appear in any tracked text file
    secrets = [s for s in (
        settings.alpaca_api_key,
        settings.alpaca_secret_key,
        getattr(settings, "operator_secret", None),
    ) if s and len(str(s)) >= 12]

    offenders: list[str] = []
    for rel in tracked:
        p = REPO / rel
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue  # binary / unreadable — skip
        for sec in secrets:
            if str(sec) in text:
                offenders.append(rel)  # filename only — never the value
                break
    assert not offenders, f"live secret VALUE found in tracked file(s): {sorted(set(offenders))} (value not shown)"

    # 3) .env.example files must hold placeholders only (no real-looking long secret)
    import re
    placeholder_ok = re.compile(r"(your[_-]|example|placeholder|xxx|<|changeme|dummy|\.\.\.)", re.I)
    for rel in tracked:
        if not rel.endswith(".env.example"):
            continue
        for line in (REPO / rel).read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            ku = key.upper()
            # credential-bearing keys only — URLs/hosts/origins are public, not secrets
            secret_bearing = any(t in ku for t in ("SECRET", "TOKEN", "PASSWORD", "API_KEY")) or ku.rstrip().endswith("_KEY")
            if not secret_bearing:
                continue
            v = val.strip().strip('"').strip("'")
            if v.lower().startswith(("http://", "https://")):
                continue  # a URL, not a secret
            if len(v) >= 16 and not placeholder_ok.search(v):
                raise AssertionError(f"{rel}: '{key.strip()}' looks like a REAL secret, not a placeholder")

    print(f"verify_no_secret_leak_in_logs_or_git: PASS (.env untracked; {len(secrets)} secret value(s) absent from "
          f"{len(tracked)} tracked files; .env.example placeholders only)")


if __name__ == "__main__":
    main()
