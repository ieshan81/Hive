"""Railway Cron helper — idempotent POST to paper scheduler tick endpoint.

Treats tick_in_progress and tick_paced as success (exit 0) so cron does not retry-storm.
Requires OPERATOR_TOKEN and HIVE_BACKEND (or defaults to localhost).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> None:
    backend = os.environ.get("HIVE_BACKEND", "http://127.0.0.1:8000").rstrip("/")
    token = os.environ.get("OPERATOR_TOKEN", "").strip()
    if not token:
        print("OPERATOR_TOKEN required")
        sys.exit(2)

    url = f"{backend}/api/autonomous-paper-learning/tick"
    req = urllib.request.Request(
        url,
        data=json.dumps({"operator": "cron"}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read()[:500]!r}")
        sys.exit(1)
    except Exception as exc:
        print(f"request failed: {exc}")
        sys.exit(1)

    status = body.get("status")
    reason = body.get("reason")
    ok_reasons = {None, "tick_paced", "tick_in_progress", "reset_in_progress"}
    if status in ("ok", "skipped", "noop") or reason in ok_reasons:
        print(f"cron_paper_scheduler_tick: OK status={status} reason={reason}")
        sys.exit(0)
    print(f"cron_paper_scheduler_tick: unexpected response={body}")
    sys.exit(1)


if __name__ == "__main__":
    main()
