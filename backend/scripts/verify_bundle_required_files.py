#!/usr/bin/env python3
"""Verify production diagnostic bundle contains required acceptance files."""

from __future__ import annotations

import io
import urllib.request
import zipfile


def main() -> None:
    backend = "https://hive-production-7343.up.railway.app"
    req = urllib.request.Request(f"{backend}/api/diagnostic-bundle/download", method="GET")
    with urllib.request.urlopen(req, timeout=240) as r:
        disp = r.headers.get("Content-Disposition", "")
        data = r.read()
    filename = disp.split("filename=")[-1].strip('"') if disp else "unknown.zip"

    z = zipfile.ZipFile(io.BytesIO(data))
    files = set(z.namelist())
    required = [
        "scanner_status.json",
        "scanner_outputs_latest.json",
        "scanner_health.json",
        "universe_pipeline.json",
        "universe_execution_shortlist.json",
        "symbol_identity.json",
        "strategy_status.json",
        "push_pull_scores.json",
        "no_trade_reason_breakdown.json",
        "strategy_verdict.json",
        "universe_discovery_backtest.json",
        "per_symbol_backtest_results.json",
        "backtest_skip_reasons.json",
        "best_symbols.json",
        "worst_symbols.json",
        "parameter_sweep_results.json",
        "sentiment_status.json",
        "sentiment_source_health.json",
        "symbol_sentiment.json",
        "news_sentiment.json",
        "social_sentiment.json",
        "finbert_inference_log.json",
        "sentiment_adjustments.json",
        "pump_dump_alerts.json",
        "ai_advisor_status.json",
        "ai_advisor_reviews.json",
        "memory_quality_report.json",
        "ai_memory_raw_events.json",
        "ai_memory_candidate.json",
        "ai_memory_validated.json",
        "ai_memory_consolidated.json",
        "ai_memory_archived.json",
        "bundle_manifest.json",
    ]
    missing = [f for f in required if f not in files]
    print("bundle_filename", filename)
    print("bundle_file_count", len(files))
    print("missing_count", len(missing))
    if missing:
        print("missing", missing)
        raise SystemExit(2)


if __name__ == "__main__":
    main()

