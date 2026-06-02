"""Phase 4 verifier: the alpha-coverage matrix tells the truth about why symbols can't trade.

Asserts every scanned crypto symbol gets an explicit alpha state (no_scorecard / unproven / rejected
/ paper_candidate), no symbol is promoted to paper_candidate without a qualifying verdict, symbol
normalization (ETHUSD == ETH/USD) cannot hide a scorecard, and productivity names the missing-alpha
blocker.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    analysis = (BACKEND / "app/services/paper_validation_analysis_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    prod = (BACKEND / "app/services/paper_validation_productivity_service.py").read_text(encoding="utf-8-sig", errors="ignore")

    # Promotion is gated on a qualifying verdict, never assumed.
    assert 'PAPER_OK = ("paper_candidate", "proven")' in analysis, "paper_candidate must require a qualifying verdict"
    assert 'verdict in PAPER_OK' in analysis, "blocker/next-evidence must key off the qualifying verdict"
    # Missing scorecard is an explicit blocker, not a silent pass.
    assert '"blocker": "NO_ALPHA_SCORECARD"' in analysis, "missing scorecard must be an explicit blocker"
    # Normalization prevents a format mismatch from hiding a scorecard.
    assert 'replace("/", "")' in analysis, "symbol normalization required (ETHUSD == ETH/USD)"
    # Symbol universe must come from real data/research sources, not the (often empty) SymbolCandidate.
    assert "HistoricalBar" in analysis and "AlphaScorecard" in analysis, "alpha universe must source from HistoricalBar UNION AlphaScorecard"
    # Productivity names the missing-alpha blocker.
    assert "NO_ALPHA_SCORECARD" in prod, "productivity must classify the missing-alpha blocker"

    from datetime import datetime

    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import AlphaScorecard, HistoricalBar, engine
    from app.services.paper_validation_analysis_service import alpha_coverage_matrix

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    # Empty DB: structurally valid, no false promotion.
    m0 = alpha_coverage_matrix(Session(engine), config={})
    for field in ("symbol_source", "scanned_symbols", "with_scorecard", "no_scorecard", "paper_candidates", "symbols"):
        assert field in m0, f"alpha matrix missing {field}"

    # Seed crypto BARS for two symbols (the real data source) + a scorecard for ONE of them stored in a
    # DIFFERENT format (BTCUSD vs BTC/USD) to prove sourcing + normalization both work.
    def _bar(sym):
        return HistoricalBar(symbol=sym, asset_class="crypto", timeframe="1Hour", timestamp=datetime.utcnow(),
                             open=1, high=1, low=1, close=1, volume=1, source="test", adjusted=False, synthetic=False)

    def _card(sym, verdict):
        return AlphaScorecard(symbol=sym, normalized_symbol=sym.replace("/", ""), asset_class="crypto",
                              strategy_family="momentum", strategy_id="s1", timeframe="1Hour", current_stage=verdict,
                              sample_size=3, backtest_count=1, walk_forward_count=0, recent_paper_trade_count=0,
                              recent_paper_pnl=0.0, recent_churn_count=0, data_freshness_status="fresh", bar_count=10,
                              quote_freshness="fresh", verdict=verdict, autonomous_generated=False, session_sample_size=0)

    with Session(engine) as s:
        s.add(_bar("BTC/USD")); s.add(_bar("ETH/USD")); s.add(_card("BTCUSD", "unproven")); s.commit()

    m = alpha_coverage_matrix(Session(engine), config={})
    assert m["scanned_symbols"] >= 2, f"matrix must source from HistoricalBar (got {m['scanned_symbols']}, source={m.get('symbol_source')})"
    assert "HistoricalBar" in (m.get("symbol_source") or []), "symbol_source must report HistoricalBar"
    by_sym = {r["symbol"]: r for r in m["symbols"]}
    btc = by_sym.get("BTC/USD") or {}
    eth = by_sym.get("ETH/USD") or {}
    # Normalization: BTC/USD bar matched the BTCUSD scorecard.
    assert btc.get("has_scorecard") is True, "ETHUSD==ETH/USD normalization must match the scorecard"
    assert btc.get("blocker") == "UNPROVEN_INSUFFICIENT_EVIDENCE", "unproven verdict must map to an explicit blocker"
    # ETH/USD has data but no scorecard -> explicit NO_ALPHA_SCORECARD.
    assert eth.get("has_scorecard") is False and eth.get("blocker") == "NO_ALPHA_SCORECARD"
    # No unqualified promotion.
    qualified = sum(1 for r in m["symbols"] if r.get("verdict") in ("paper_candidate", "proven"))
    assert m["paper_candidates"] == qualified == 0, "no symbol may be promoted without a qualifying verdict"

    print(f"verify_alpha_scorecard_coverage_truth: PASS (sources HistoricalBar+AlphaScorecard={m.get('symbol_source')}; "
          f"normalization matched BTCUSD->BTC/USD; explicit state per symbol; no unqualified promotion)")


if __name__ == "__main__":
    main()
