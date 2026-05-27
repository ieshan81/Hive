"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Brain,
  Hexagon,
  Shield,
  TrendingUp,
  Wallet,
  Zap,
  AlertTriangle,
  Radar,
} from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { WhyNoTradeCard } from "@/components/panels/WhyNoTradeCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";
import { symbolIdentity } from "@/lib/symbolIdentity";

type Cockpit = {
  cockpit_bar?: Record<string, string | boolean | number | null | undefined>;
  mission_summary?: Record<string, string | boolean | number | null | undefined>;
  hive_brain_preview?: {
    meaningful_memory_count?: number;
    validated_count?: number;
    consolidated_count?: number;
    categories?: Record<string, number>;
    latest_lesson?: { title?: string; summary?: string };
  };
  account_survival?: Record<string, number | string | null | undefined>;
  capital_allocator?: {
    detail?: Record<string, number | null | undefined>;
    sparkline?: number[];
    headline?: string;
    status?: string;
  };
  ai_fund_manager?: {
    active?: boolean;
    configured?: boolean;
    current_decision?: string;
    confidence?: number;
    reason_summary?: string;
    sentiment_engines?: Record<string, { active?: boolean; wired?: boolean; reason?: string }>;
  };
  push_pull_engine?: Record<string, unknown>;
  strategy_status?: { active?: boolean; signal_formula_summary?: string; entry_blocks?: string[] };
  paper_learning?: Record<string, unknown>;
  latest_insight?: { narrative?: string; tick?: Record<string, unknown> };
  risk_cage?: Record<string, unknown>;
  capital_graph?: { points?: { t?: string; equity?: number }[] };
  market_radar?: {
    top_active_candidates?: { symbol?: string; status?: string; blocked_reason?: string }[];
  };
  universe_mode?: { mode_label?: string; stocks_session_note?: string };
  exit_monitor?: { open_positions_count?: number; plain?: string };
  can_place_paper_orders?: boolean;
  primary_blocker_plain?: string;
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/5 bg-black/20 px-3 py-2">
      <p className="text-[9px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-sm font-semibold text-white mt-0.5 truncate">{value}</p>
    </div>
  );
}

function HoneycombBg() {
  return (
    <div
      className="pointer-events-none absolute inset-0 opacity-[0.07]"
      style={{
        backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='56' height='100'%3E%3Cpath d='M28 0 L56 16 L56 48 L28 64 L0 48 L0 16 Z' fill='none' stroke='%2300d1ff' stroke-width='1'/%3E%3C/svg%3E")`,
        backgroundSize: "56px 100px",
      }}
    />
  );
}

export function MissionControlPanel() {
  const [data, setData] = useState<Cockpit | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await apiGet<Cockpit>("/api/mission-control/status");
    if (res.ok && res.data) {
      setData(res.data);
      setError(null);
    } else {
      setError(res.error || `HTTP ${res.status}`);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  if (loading) return <EmptyState message="Loading Mission Control cockpit…" className="min-h-[320px]" />;
  if (error) {
    return (
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-amber-200 text-sm">
        Mission Control unavailable: {error}
      </div>
    );
  }

  const bar = data?.cockpit_bar ?? {};
  const acct = data?.account_survival ?? {};
  const alloc = data?.capital_allocator?.detail ?? {};
  const spark = data?.capital_allocator?.sparkline ?? [];
  const maxSpark = Math.max(...spark, acct.current_paper_equity as number ?? 1, 1);
  const graph = data?.capital_graph?.points ?? [];
  const maxEq = Math.max(...graph.map((p) => p.equity ?? 0), 1);
  const hive = data?.hive_brain_preview ?? {};
  const ai = data?.ai_fund_manager ?? {};
  const radar = data?.market_radar?.top_active_candidates ?? [];

  return (
    <section className="relative space-y-4 max-w-6xl">
      <HoneycombBg />

      <header className="relative rounded-2xl border border-hive-cyan/20 bg-gradient-to-br from-hive-cyan/10 via-violet-950/20 to-black/40 p-5 overflow-hidden">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <Hexagon className="h-7 w-7 text-hive-cyan" />
              Mission Control
            </h1>
            <p className="text-sm text-slate-300 mt-1 max-w-2xl">{data?.mission_summary?.headline as string}</p>
            <p className="text-xs text-slate-500 mt-1">{data?.mission_summary?.engine_doing as string}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(bar).slice(0, 6).map(([k, v]) => (
              <span key={k} className="text-[10px] px-2 py-1 rounded-full border border-white/10 bg-black/30 text-slate-300">
                {k.replace(/_/g, " ")}: <span className="text-hive-cyan">{String(v)}</span>
              </span>
            ))}
          </div>
        </div>
        {!data?.can_place_paper_orders && data?.primary_blocker_plain && (
          <p className="text-sm text-amber-200 mt-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" /> {data.primary_blocker_plain}
          </p>
        )}
      </header>

      <div className="relative grid gap-4 lg:grid-cols-3">
        <GlassPanel title="Account survival" icon={<Wallet className="h-4 w-4" />} className="lg:col-span-1">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Equity" value={`$${Number(acct.current_paper_equity ?? 0).toFixed(2)}`} />
            <Stat label="Buying power" value={`$${Number(acct.buying_power ?? 0).toFixed(2)}`} />
            <Stat label="Open P/L" value={`$${Number(acct.unrealized_pl ?? 0).toFixed(2)}`} />
            <Stat label="Today P/L" value={`$${Number(acct.today_pl ?? 0).toFixed(2)}`} />
            <Stat label="Total P/L" value={`$${Number(acct.total_pl ?? 0).toFixed(2)}`} />
            <Stat label="Sync" value={String(acct.broker_sync_status ?? "—")} />
          </div>
        </GlassPanel>

        <GlassPanel title="Capital allocator" icon={<TrendingUp className="h-4 w-4" />} className="lg:col-span-1">
          <div className="grid grid-cols-2 gap-2 text-sm">
            <Stat label="Deployable" value={`$${alloc.deployable_capital ?? "—"}`} />
            <Stat label="Cash reserve" value={`$${alloc.cash_reserve ?? "—"}`} />
            <Stat label="Crypto budget" value={`$${alloc.crypto_budget ?? "—"}`} />
            <Stat label="Stock budget" value={`$${alloc.stock_budget ?? "—"}`} />
          </div>
          {spark.length > 0 && (
            <div className="flex items-end gap-0.5 h-10 mt-3">
              {spark.map((v, i) => (
                <div
                  key={i}
                  className="flex-1 bg-violet-500/50 rounded-t min-w-[2px]"
                  style={{ height: `${Math.max(8, (v / maxSpark) * 100)}%` }}
                />
              ))}
            </div>
          )}
        </GlassPanel>

        <GlassPanel title="Hive brain preview" icon={<Brain className="h-4 w-4" />} className="lg:col-span-1">
          <p className="text-xs text-slate-400">
            Meaningful: {hive.meaningful_memory_count ?? 0} · Validated: {hive.validated_count ?? 0} · Consolidated:{" "}
            {hive.consolidated_count ?? 0}
          </p>
          <div className="grid grid-cols-2 gap-1 mt-2 text-[10px] text-slate-500">
            {Object.entries(hive.categories ?? {}).map(([k, v]) => (
              <span key={k}>
                {k}: <span className="text-slate-300">{v}</span>
              </span>
            ))}
          </div>
          {hive.latest_lesson?.summary && (
            <p className="text-[11px] text-cyan-200/90 mt-2 line-clamp-3">{hive.latest_lesson.summary}</p>
          )}
        </GlassPanel>
      </div>

      <div className="relative grid gap-4 lg:grid-cols-2">
        <WhyNoTradeCard />
        <GlassPanel title="AI fund manager" icon={<Brain className="h-4 w-4" />}>
          <p className="text-xs text-slate-400 mb-2">
            Status:{" "}
            <span className={ai.active ? "text-emerald-400" : "text-amber-400"}>
              {ai.active ? "Gemini advisor active (advisory only)" : "Inactive or not configured"}
            </span>
          </p>
          <p className="text-sm text-white">Decision: {ai.current_decision ?? "—"}</p>
          <p className="text-[11px] text-slate-500 mt-1 line-clamp-3">{ai.reason_summary}</p>
          <div className="mt-2 space-y-1">
            {Object.entries(ai.sentiment_engines ?? {})
              .slice(0, 4)
              .map(([k, v]) => (
                <p key={k} className="text-[10px] text-slate-500">
                  {k}: {v?.active ? "active" : "inactive"} — {v?.reason?.slice(0, 60)}
                </p>
              ))}
          </div>
        </GlassPanel>

        <GlassPanel title="Push-pull engine" icon={<Zap className="h-4 w-4" />}>
          <p className="text-sm text-white">{String((data?.push_pull_engine as { market_mode_label?: string })?.market_mode_label ?? "—")}</p>
          <p className="text-[11px] text-slate-500 mt-1">{data?.strategy_status?.signal_formula_summary}</p>
          <p className="text-[10px] text-slate-600 mt-2">
            Strategy active: {data?.strategy_status?.active ? "yes" : "no"} · Exit monitor:{" "}
            {data?.exit_monitor?.plain ?? "idle"}
          </p>
        </GlassPanel>
      </div>

      <GlassPanel title="Capital graph" icon={<TrendingUp className="h-4 w-4" />}>
        {graph.length === 0 ? (
          <p className="text-sm text-slate-500">Equity curve populates after broker sync snapshots.</p>
        ) : (
          <div className="flex items-end gap-0.5 h-32">
            {graph.slice(-40).map((p, i) => (
              <div
                key={`${p.t}-${i}`}
                className="flex-1 bg-gradient-to-t from-hive-cyan/20 to-hive-cyan/70 rounded-t min-w-[3px]"
                style={{ height: `${Math.max(6, ((p.equity ?? 0) / maxEq) * 100)}%` }}
                title={`${p.t}: $${p.equity?.toFixed(2)}`}
              />
            ))}
          </div>
        )}
        <p className="text-[10px] text-slate-500 mt-2">
          Current equity: ${Number(acct.current_paper_equity ?? 0).toFixed(2)} · Mode: {data?.universe_mode?.mode_label}
        </p>
      </GlassPanel>

      <GlassPanel title="Market radar" icon={<Radar className="h-4 w-4" />}>
        {radar.length === 0 ? (
          <p className="text-sm text-slate-500">No active candidates right now. {data?.universe_mode?.stocks_session_note}</p>
        ) : (
          <ul className="space-y-2">
            {radar.map((c) => {
              const id = symbolIdentity(c.symbol ?? "");
              return (
                <li key={c.symbol} className="flex items-center gap-3 text-sm border-b border-white/5 pb-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-hive-cyan/10 text-hive-cyan font-bold text-xs">
                    {id.glyph || id.name.slice(0, 2)}
                  </span>
                  <div>
                    <p className="text-white font-medium">{c.symbol}</p>
                    <p className="text-[10px] text-slate-500">{id.name} · {c.status}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </GlassPanel>

      <GlassPanel title="Latest insight" icon={<Activity className="h-4 w-4" />}>
        <p className="text-sm text-white">{data?.latest_insight?.narrative ?? "Waiting for next scheduler tick."}</p>
        <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
          <span className="text-slate-500">Risk cage: live locked</span>
          <span className="text-slate-500">Stale data guard: on</span>
          <span className="text-slate-500">Duplicate entry protection: on</span>
        </div>
      </GlassPanel>

      <div className="relative flex items-center gap-2 text-[10px] text-emerald-400/80">
        <Shield className="h-3.5 w-3.5" />
        Paper only · Live trading locked · Engine live-ready in discipline, paper-only at runtime
      </div>
    </section>
  );
}
