"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, Play, RefreshCw, Zap, Shield, TrendingUp } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { CandleChartPanel } from "@/components/panels/CandleChartPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type Cockpit = {
  generated_at_utc?: string;
  live_truth?: boolean;
  ai_cockpit_message?: string;
  watchlist?: { total?: number; crypto?: { usd_pairs?: number } };
  funnel?: Record<string, number>;
  shortlist?: Array<{ symbol: string; universe_rank_score?: number }>;
  why_zero_shortlist?: string;
  scores?: Array<{ symbol: string; pass?: boolean; quality_score?: number; push_score?: number }>;
  passed_count?: number;
  control?: {
    can_place_paper_orders?: boolean;
    paper_learning_on?: boolean;
    bot_can_place?: boolean;
    blockers?: string[];
    mode?: string;
  };
  account?: { equity?: number; daily_pl?: number };
  positions?: Array<{ symbol: string; qty: number; unrealized_pl?: number }>;
  recent_trades?: Array<{ symbol: string; side: string; status: string }>;
  weights?: { universe_ranking?: Record<string, number>; min_rank_score?: number };
};

export function CockpitDashboard() {
  const [data, setData] = useState<Cockpit | null>(null);
  const [loading, setLoading] = useState(true);
  const [cycleBusy, setCycleBusy] = useState(false);
  const [bootstrapBusy, setBootstrapBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    const r = await apiGet<Cockpit>("/api/v2/cockpit", { timeoutMs: 60000 });
    if (r.ok && r.data) setData(r.data);
    else setErr(r.error || "Cockpit unavailable");
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  const runCycle = async () => {
    setCycleBusy(true);
    const r = await apiPostOperator("/api/v2/cycle/run", { operator: "cockpit" });
    if (!r.ok) setErr(r.error || "Cycle failed");
    await load();
    setCycleBusy(false);
  };

  const bootstrap = async () => {
    if (!confirm("Bootstrap V2: reset learning state, refresh major watchlist bars, enable paper learning, run cycle?")) return;
    setBootstrapBusy(true);
    const r = await apiPostOperator("/api/v2/bootstrap", { operator: "cockpit", nuke_first: false });
    if (!r.ok) setErr(r.error || "Bootstrap failed");
    await load();
    setBootstrapBusy(false);
  };

  const f = data?.funnel ?? {};
  const ctrl = data?.control ?? {};

  return (
    <div className="space-y-4 max-w-6xl">
      <header>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Brain className="h-7 w-7 text-hive-cyan" />
          AI Trading Cockpit
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Research v2 — live Alpaca truth, dynamic SL/TP, AI adjusts weights only (never executes).
        </p>
        {data?.ai_cockpit_message && (
          <p className="text-xs text-hive-cyan/90 mt-2 border border-hive-cyan/20 rounded-lg px-3 py-2 bg-hive-cyan/5">
            {data.ai_cockpit_message}
          </p>
        )}
        {err && <p className="text-xs text-amber-400 mt-2">{err}</p>}
      </header>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded border border-white/10 text-slate-300 hover:bg-white/5"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh live
        </button>
        <button
          type="button"
          onClick={runCycle}
          disabled={cycleBusy}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded border border-[#00FF66]/40 text-[#00FF66] hover:bg-[#00FF66]/10"
        >
          <Zap className="h-3.5 w-3.5" />
          {cycleBusy ? "Running cycle…" : "Run trading cycle"}
        </button>
        <button
          type="button"
          onClick={bootstrap}
          disabled={bootstrapBusy}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded border border-hive-cyan/40 text-hive-cyan hover:bg-hive-cyan/10"
        >
          <Play className="h-3.5 w-3.5" />
          {bootstrapBusy ? "Bootstrapping…" : "Bootstrap V2"}
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        {[
          ["Paper learning", ctrl.paper_learning_on ? "ON" : "OFF", ctrl.paper_learning_on ? "#00FF66" : "#F59E0B"],
          ["Bot can trade", ctrl.bot_can_place ? "YES" : "NO", ctrl.bot_can_place ? "#00FF66" : "#F59E0B"],
          ["Equity", data?.account?.equity != null ? `$${data.account.equity.toFixed(2)}` : "—", "#fff"],
          ["Watchlist", String(data?.watchlist?.crypto?.usd_pairs ?? 0), "#00dbe9"],
        ].map(([label, val, color]) => (
          <div key={label} className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="text-[10px] uppercase text-slate-500">{label}</p>
            <p className="text-lg font-bold mono-metric" style={{ color }}>
              {val}
            </p>
          </div>
        ))}
      </div>

      <GlassPanel title="Live funnel (no cache)" icon={<TrendingUp className="h-4 w-4" />}>
        <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
          {[
            ["Available", f.available],
            ["Cached", f.cached],
            ["Fresh", f.fresh],
            ["Eligible", f.eligible],
            ["Ranked", f.ranked],
            ["Shortlist", f.shortlist],
          ].map(([label, v]) => (
            <div key={String(label)} className="text-center p-2 rounded border border-white/5">
              <p className="text-[9px] text-slate-500 uppercase">{label}</p>
              <p className="text-lg font-bold text-white">{String(v ?? 0)}</p>
            </div>
          ))}
        </div>
        {data?.why_zero_shortlist && (
          <p className="text-[10px] text-amber-300 mt-2">{data.why_zero_shortlist}</p>
        )}
      </GlassPanel>

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassPanel title="Execution shortlist" icon={<Shield className="h-4 w-4" />}>
          {(data?.shortlist?.length ?? 0) === 0 ? (
            <p className="text-[11px] text-slate-500">No shortlist — run cycle after bar refresh.</p>
          ) : (
            <ul className="space-y-1">
              {data?.shortlist?.map((s) => (
                <li key={s.symbol} className="text-[11px] text-white flex justify-between">
                  <span>{s.symbol}</span>
                  <span className="text-hive-cyan mono-metric">
                    {((s.universe_rank_score ?? 0) * 100).toFixed(0)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </GlassPanel>

        <GlassPanel title="Live scores" icon={<Zap className="h-4 w-4" />}>
          <p className="text-[10px] text-slate-500 mb-2">{data?.passed_count ?? 0} passed push-pull gates</p>
          <ul className="space-y-1 max-h-[180px] overflow-y-auto">
            {(data?.scores ?? []).slice(0, 8).map((s) => (
              <li key={s.symbol} className="text-[10px] flex justify-between text-slate-300">
                <span>{s.symbol}</span>
                <span style={{ color: s.pass ? "#00FF66" : "#849495" }}>
                  Q{(s.quality_score ?? 0).toFixed(0)} P{(s.push_score ?? 0).toFixed(0)}
                </span>
              </li>
            ))}
          </ul>
        </GlassPanel>
      </div>

      <CandleChartPanel defaultSymbol={(data?.shortlist?.[0]?.symbol as string) || "BTC/USD"} />

      <GlassPanel title="Recent paper trades">
        {(data?.recent_trades?.length ?? 0) === 0 ? (
          <p className="text-[11px] text-slate-500">No trades yet — bootstrap + run cycle.</p>
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
        Live @ {data?.generated_at_utc?.slice(0, 19) ?? "—"} · cached_snapshot=false
      </p>
    </div>
  );
}
