"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, RefreshCw, Zap, Shield, TrendingUp, Skull } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { CandleChartPanel } from "@/components/panels/CandleChartPanel";
import { CockpitFunnelBrain } from "@/components/cockpit/CockpitFunnelBrain";
import { apiGet, apiPostOperator } from "@/lib/apiClient";
import { dispatchCockpitRefresh } from "@/lib/cockpitEvents";

type Cockpit = {
  generated_at_utc?: string;
  live_truth?: boolean;
  ai_cockpit_message?: string;
  watchlist?: {
    total?: number;
    crypto?: { usd_pairs?: number; symbols?: string[] };
    stocks?: { count?: number; symbols?: string[] };
  };
  funnel?: Record<string, number>;
  shortlist?: Array<{ symbol: string; universe_rank_score?: number }>;
  why_zero_shortlist?: string;
  scores?: Array<{
    symbol: string;
    pass?: boolean;
    entry_allowed?: boolean;
    quality_score?: number;
    push_score?: number;
  }>;
  passed_count?: number;
  control?: {
    can_place_paper_orders?: boolean;
    paper_learning_on?: boolean;
    bot_can_place?: boolean;
    blockers?: string[];
    mode?: string;
  };
  account?: { connected?: boolean; equity?: number; daily_pl?: number };
  alpaca_connected?: boolean;
  positions?: Array<{ symbol: string; qty: number; unrealized_pl?: number }>;
  recent_trades?: Array<{ symbol: string; side: string; status: string }>;
  weights?: { universe_ranking?: Record<string, number>; min_rank_score?: number };
};

const REBUILD_TIMEOUT_MS = 180000;

export function CockpitDashboard() {
  const [data, setData] = useState<Cockpit | null>(null);
  const [loading, setLoading] = useState(true);
  const [cycleBusy, setCycleBusy] = useState(false);
  const [rebuildBusy, setRebuildBusy] = useState(false);
  const [rebuildLog, setRebuildLog] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    const r = await apiGet<Cockpit>("/api/cockpit", { timeoutMs: 20000 });
    if (r.ok && r.data) {
      setData(r.data);
      dispatchCockpitRefresh(r.data as Record<string, unknown>);
      setDetailsLoading(true);
      const full = await apiGet<Cockpit>("/api/cockpit?details=1", { timeoutMs: 120000 });
      if (full.ok && full.data) {
        setData((prev) => ({ ...prev, ...full.data, control: full.data?.control ?? prev?.control }));
        dispatchCockpitRefresh(full.data as Record<string, unknown>);
      }
      setDetailsLoading(false);
    } else {
      setErr(r.error || "Cockpit unavailable — check API_URL on Railway frontend");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 25000);
    return () => clearInterval(t);
  }, [load]);

  const runCycle = async () => {
    setCycleBusy(true);
    setErr(null);
    const r = await apiPostOperator("/api/agent/cycle", { operator: "cockpit" }, { timeoutMs: 120000 });
    if (!r.ok) setErr(r.error || "Cycle failed");
    await load();
    setCycleBusy(false);
  };

  const hardRebuild = async () => {
    if (
      !confirm(
        "HARD NUKE + REBUILD: Deletes all trades, bars, memories, and brain data. Rebuilds aggressive V2 agent on Alpaca paper. Continue?"
      )
    )
      return;
    setRebuildBusy(true);
    setRebuildLog("Nuking database and clearing caches…");
    setErr(null);
    const r = await apiPostOperator(
      "/api/rebuild",
      { operator: "cockpit" },
      { timeoutMs: REBUILD_TIMEOUT_MS }
    );
    if (!r.ok) {
      setErr(r.error || "Rebuild failed or timed out — check Railway logs");
      setRebuildLog(null);
    } else {
      const msg = (r.data as { message?: string })?.message || "Rebuild complete";
      const can = (r.data as { can_trade?: boolean })?.can_trade;
      setRebuildLog(`${msg} · Bot can trade: ${can ? "YES" : "NO"}`);
    }
    await load();
    setRebuildBusy(false);
  };

  const f = data?.funnel ?? {};
  const ctrl = data?.control ?? {};
  const chartSymbol =
    data?.shortlist?.[0]?.symbol ||
    data?.scores?.find((s) => s.pass || s.entry_allowed)?.symbol ||
    "BTC/USD";

  return (
    <div className="space-y-4 max-w-6xl">
      <header>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Brain className="h-7 w-7 text-hive-cyan" />
          AI Trading Cockpit
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Research v2 — live Alpaca crypto + stocks, dynamic SL/TP, aggressive paper cycles. No snapshot cache.
        </p>
        {data?.ai_cockpit_message && (
          <p className="text-xs text-hive-cyan/90 mt-2 border border-hive-cyan/20 rounded-lg px-3 py-2 bg-hive-cyan/5">
            {data.ai_cockpit_message}
          </p>
        )}
        {rebuildLog && (
          <p className="text-xs text-[#00FF66]/90 mt-2 border border-[#00FF66]/20 rounded-lg px-3 py-2">
            {rebuildLog}
          </p>
        )}
        {err && (
          <p className="text-xs text-amber-400 mt-2">
            {err}
            <span className="block text-slate-500 mt-1">
              Top banner and cards use the same /api/cockpit source. If you see &quot;Not Found&quot;, redeploy backend +
              frontend from latest main.
            </span>
          </p>
        )}
        {detailsLoading && <p className="text-[10px] text-slate-500 mt-1">Loading live scores…</p>}
      </header>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={load}
          disabled={loading || rebuildBusy}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded border border-white/10 text-slate-300 hover:bg-white/5"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh live
        </button>
        <button
          type="button"
          onClick={hardRebuild}
          disabled={rebuildBusy}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded border border-red-500/50 text-red-300 hover:bg-red-500/10"
        >
          <Skull className="h-3.5 w-3.5" />
          {rebuildBusy ? "Rebuilding… (up to 3 min)" : "Hard nuke + rebuild"}
        </button>
        <button
          type="button"
          onClick={runCycle}
          disabled={cycleBusy || rebuildBusy}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded border border-[#00FF66]/40 text-[#00FF66] hover:bg-[#00FF66]/10"
        >
          <Zap className="h-3.5 w-3.5" />
          {cycleBusy ? "Agent cycle…" : "Run agent cycle"}
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
        {[
          ["Paper learning", ctrl.paper_learning_on ? "ON" : "OFF", ctrl.paper_learning_on ? "#00FF66" : "#F59E0B"],
          ["Bot can trade", ctrl.bot_can_place ? "YES" : "NO", ctrl.bot_can_place ? "#00FF66" : "#F59E0B"],
          ["Equity", data?.account?.equity != null ? `$${data.account.equity.toFixed(2)}` : "—", "#fff"],
          [
            "Crypto pairs",
            String(data?.watchlist?.crypto?.usd_pairs ?? data?.watchlist?.crypto?.symbols?.length ?? 0),
            "#00dbe9",
          ],
          [
            "Stocks",
            String(data?.watchlist?.stocks?.count ?? data?.watchlist?.stocks?.symbols?.length ?? 0),
            "#00dbe9",
          ],
          [
            "Alpaca",
            data?.account?.connected || data?.alpaca_connected ? "CONNECTED" : "OFFLINE",
            data?.account?.connected || data?.alpaca_connected ? "#00FF66" : "#EF4444",
          ],
        ].map(([label, val, color]) => (
          <div key={label} className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="text-[10px] uppercase text-slate-500">{label}</p>
            <p className="text-lg font-bold mono-metric" style={{ color }}>
              {val}
            </p>
          </div>
        ))}
      </div>

      <CockpitFunnelBrain
        funnel={f}
        blockers={data?.why_zero_shortlist}
        aiNote={data?.ai_cockpit_message}
      />

      <CandleChartPanel defaultSymbol={chartSymbol} />

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassPanel title="Shortlist" icon={<Shield className="h-4 w-4" />}>
          {(data?.shortlist?.length ?? 0) === 0 ? (
            <p className="text-[11px] text-slate-500">Empty — run agent cycle after rebuild.</p>
          ) : (
            <ul className="space-y-1">
              {data?.shortlist?.map((s) => (
                <li key={s.symbol} className="text-[11px] flex justify-between text-white">
                  <span>{s.symbol}</span>
                  <span className="text-hive-cyan">
                    {((s.universe_rank_score ?? 0) * 100).toFixed(0)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </GlassPanel>

        <GlassPanel title="Live scores (push-pull + patterns)">
          <p className="text-[10px] text-slate-500 mb-2">{data?.passed_count ?? 0} passed gates</p>
          <ul className="space-y-1 max-h-[200px] overflow-y-auto">
            {(data?.scores ?? []).map((s) => (
              <li key={s.symbol} className="text-[10px] flex justify-between">
                <span className="text-slate-300">{s.symbol}</span>
                <span style={{ color: s.pass || s.entry_allowed ? "#00FF66" : "#849495" }}>
                  Q{(s.quality_score ?? 0).toFixed(0)} · P{(s.push_score ?? 0).toFixed(0)}
                  {s.entry_allowed ? " · GO" : ""}
                </span>
              </li>
            ))}
          </ul>
        </GlassPanel>
      </div>

      <GlassPanel title="Recent paper trades">
        {(data?.recent_trades?.length ?? 0) === 0 ? (
          <p className="text-[11px] text-slate-500">No trades yet — hard rebuild then run agent cycle.</p>
        ) : (
          <ul className="space-y-1">
            {data?.recent_trades?.map((t, i) => (
              <li key={i} className="text-[10px] text-slate-300">
                {t.symbol} {t.side} — {t.status}
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>

      <p className="text-[9px] text-slate-600">
        Live @ {data?.generated_at_utc?.slice(0, 19) ?? "—"} · scheduler ~45s when paper learning ON
      </p>
    </div>
  );
}
