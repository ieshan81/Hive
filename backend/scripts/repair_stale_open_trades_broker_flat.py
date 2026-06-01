"""Dry-run/apply repair for stale local open TradeRecord rows when broker is flat.

Default is dry-run. Use --apply to mutate. Never deletes records.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session  # noqa: E402

from app.database import engine, init_db  # noqa: E402
from app.services.config_manager import ConfigManager  # noqa: E402
from app.services.trade_state_repair_service import TradeStateRepairService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Mutate stale local TradeRecord rows.")
    parser.add_argument("--symbol", action="append", default=[], help="Restrict repair to one symbol; can repeat.")
    args = parser.parse_args()

    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        svc = TradeStateRepairService(session, cfg)
        out = svc.repair_stale_open_trades_when_broker_flat(
            dry_run=not args.apply,
            symbols=args.symbol or None,
            require_no_broker_positions=True,
        )
        print(out)
        if args.apply and out.get("status") == "ok":
            session.commit()
        elif args.apply:
            session.rollback()
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
