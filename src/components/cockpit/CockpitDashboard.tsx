"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Activity, ChevronDown, RefreshCw } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { CockpitAutopilotChip } from "@/components/cockpit/CockpitAutopilotChip";
import { CockpitFunnelBrain } from "@/components/cockpit/CockpitFunnelBrain";
import { CockpitPortfolioHistory } from "@/components/cockpit/CockpitPortfolioHistory";
import { WhyNoTradeCard } from "@/components/panels/WhyNoTradeCard";
import { apiGet } from "@/lib/apiClient";
import { dispatchCockpitRefresh } from "@/lib/cockpitEvents";

type Cockpit = {
  generated_at_utc?: string;
  funnel?: Record<string, number>;
  eligible_trades?: Array<{ symbol: string; trade_quality_score?: number; universe_rank_score?: number; stop_loss?: number; take_profit?: number }>;
  shortlist?: Array<{ symbol: string; trade_quality_score?: number }>;
  scores?: Array<{ symbol: string; entry_allowed?: boolean; trade_quality_score?: number }>;
  why_no_trade_summary?: { plain?: string; top_blockers?: Array<{ code?: string; count?: number; label?: string }> };
  universe?: {
    top_blockers?: Array<{ code?: string; count?: number; label?: string }>;
    top_candidates?: Array<{ symbol?: string; trade_quality_score?: number; no_trade_reason?: string }>;
    funnel?: { eligible?: number; shortlisted?: number };
  };
  account?: { connected?: boolean; equity?: number; daily_pl?: number };
  alpaca_connected?: boolean;
  positions?: Array<{ symbol: string; qty: number }>;
  recent_trades?: Array<{ symbol: string; side: string; status: string }>;
  alpha_factory?: {
    can_trade_paper_now?: boolean;
    paper_candidate_count?: number;
    plain_english?: string;
    paper_exploration_allowed?: boolean;
    best_candidate?: { symbol?: string } | null;
  };
  paper_execution?: {
    paper_broker_connected?: boolean;
    paper_orders_enabled?: boolean;
    paper_learning_on?: boolean;
    scheduler_enabled?: boolean;
    open_positions_count?: number;
    active_orders_count?: number;
    new_entries_allowed?: boolean;
    exits_allowed?: boolean;
    next_action?: string;
    blockers?: string[];
    live_trading_locked?: boolean;
  };
};

function dedupeEligible<T extends { symbol: string; trade_quality_score?: number; universe_rank_score?: number }>(
  rows: T[]
): T[] {
  const best = new Map<string, T>();
  for (const row of rows.filter((r) => r.symbol)) {
    const key = String(row.symbol).toUpperCase().replace(/[/-]/g, "");
    const prev = best.get(key);
    const prevScore = Number(prev?.universe_rank_score ?? prev?.trade_quality_score ?? 0);
    const nextScore = Number(row.universe_rank_score ?? row.trade_quality_score ?? 0);
    if (!prev || nextScore >= prevScore) best.set(key, row);
  }
  return Array.from(best.values());
}

export function CockpitDashboard() {
  const [data, setData] = useState<Cockpit | null>(null);
  const [tiles, setTiles] = useState<Cockpit | null>(null);
  const [tilesStale, setTilesStale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [showMore, setShowMore] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    apiGet<Cockpit>("/api/mission-control/status", { timeoutMs: 12000 }).then((statusRes) => {
      if (statusRes.ok && statusRes.data) {
        setData(statusRes.data);
        dispatchCockpitRefresh(statusRes.data as Record<string, unknown>);
      } else {
        setErr(statusRes.error || "Cockpit unavailable");
      }
    });
    const tilesRes = await apiGet<Cockpit>("/api/mission-control/tiles", { timeoutMs: 5000 });
    if (tilesRes.ok && tilesRes.data) {
      setTiles(tilesRes.data);
      setTilesStale(false);
    } else {
      setTilesStale(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 25000);
    return () => clearInterval(t);
  }, [load]);

  const tileSrc = tiles ?? data;
  const paper = tileSrc?.paper_execution ?? {};
  const universe = data?.universe ?? {};
  const f = data?.funnel ?? universe.funnel ?? {};
  const tilesUnknown = tilesStale || (loading && !tiles);
  const canSubmitEntries = Boolean(paper.new_entries_allowed ?? paper.paper_orders_enabled);
  const exitsAllowed = Boolean(paper.exits_allowed ?? paper.paper_broker_connected);
  const eligible = dedupeEligible(
    data?.eligible_trades ?? data?.shortlist ?? (data?.scores ?? []).filter((s) => s.entry_allowed) ?? []
  );
  const topCandidate = universe.top_candidates?.[0] ?? eligible[0] ?? null;

  const statusTiles = [
    ["Scheduler", tilesUnknown ? "—" : paper.scheduler_enabled ? "ON" : "OFF", paper.scheduler_enabled],
    ["Paper broker", tilesUnknown ? "—" : paper.paper_broker_connected ? "ON" : "OFF", paper.paper_broker_connected],
    ["Entries", tilesUnknown ? "—" : canSubmitEntries ? "READY" : "PAUSED", canSubmitEntries],
    ["Live $", "LOCKED", true],
  ] as const;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-4 px-1 sm:px-2">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
            <Activity className="h-7 w-7 text-hive-cyan" />
            Mission Control
          </h1>
          <p className="mt-1 text-sm text-slate-400">Is the system safe and running? · live locked · paper only</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 rounded border border-white/10 px-3 py-2 text-xs text-slate-300 hover:bg-white/5"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <CockpitAutopilotChip />
        </div>
      </header>

      {err ? <p className="text-xs text-amber-400">{err}</p> : null}

      {!tilesUnknown && paper.scheduler_enabled === false ? (
        <div
          className="rounded-xl border-2 border-red-500/60 bg-red-950/40 px-4 py-3"
          role="alert"
        >
          <p className="text-sm font-bold text-red-300">Scheduler OFF</p>
          <p className="mt-1 text-xs text-red-200/90">
            Paper is ready but automatic push-pull ticks are disabled. Enable the scheduler in Settings
            or via operator API — live trading stays locked.
          </p>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {statusTiles.map(([label, val, ok]) => (
          <div key={label} className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="text-[10px] uppercase text-slate-500">{label}</p>
            <p
              className="text-base font-bold mono-metric"
              style={{
                color: label === "Live $" ? "#FB7185" : tilesUnknown ? "#64748B" : ok ? "#00FF66" : "#F59E0B",
              }}
            >
              {val}
            </p>
          </div>
        ))}
      </div>

      <WhyNoTradeCard
        plain={data?.why_no_trade_summary?.plain ?? paper.next_action}
        topBlockers={universe.top_blockers ?? data?.why_no_trade_summary?.top_blockers ?? []}
        topCandidate={topCandidate}
        shortlisted={Number(f.shortlisted ?? 0)}
        eligible={Number(f.eligible ?? 0)}
        canPlacePaperOrders={canSubmitEntries}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassPanel title="Runtime snapshot">
          <ul className="space-y-1 text-xs text-slate-300">
            <li>Equity {tileSrc?.account?.equity != null ? `$${tileSrc.account.equity}` : "—"}</li>
            <li>
              Positions {paper.open_positions_count ?? 0} · Orders {paper.active_orders_count ?? 0}
            </li>
            <li>Exits {exitsAllowed ? "allowed" : "blocked"}</li>
            <li>
              Shadow learning{" "}
              <Link href="/shadow-league" className="text-hive-cyan hover:underline">
                view league →
              </Link>
            </li>
          </ul>
        </GlassPanel>
        <CockpitFunnelBrain funnel={f} blockers={data?.why_no_trade_summary?.plain} />
      </div>

      <button
        type="button"
        onClick={() => setShowMore((v) => !v)}
        className="flex w-full items-center justify-center gap-1 rounded-lg border border-white/10 py-2 text-xs text-slate-400 hover:bg-white/5"
      >
        <ChevronDown className={`h-4 w-4 transition-transform ${showMore ? "rotate-180" : ""}`} />
        {showMore ? "Hide" : "Show"} portfolio & trade history
      </button>

      {showMore ? (
        <div className="space-y-4">
          <CockpitPortfolioHistory />
          <GlassPanel title="Eligible setups">
            {eligible.length === 0 ? (
              <p className="text-[11px] text-slate-500">None this scan.</p>
            ) : (
              <ul className="max-h-48 space-y-1 overflow-y-auto">
                {eligible.slice(0, 12).map((row) => {
                  const score = Number(
                    (row as { universe_rank_score?: number }).universe_rank_score ?? row.trade_quality_score ?? 0
                  );
                  return (
                  <li key={row.symbol} className="flex justify-between border-b border-white/5 py-1 text-[11px] text-white">
                    <TickerSymbol symbol={row.symbol} size="sm" labelClassName="text-[11px]" />
                    <span className="text-hive-cyan shrink-0">Q{Math.round(score * 100)}</span>
                  </li>
                  );
                })}
              </ul>
            )}
          </GlassPanel>
          <GlassPanel title="Recent paper trades">
            {(data?.recent_trades?.length ?? 0) === 0 ? (
              <p className="text-[11px] text-slate-500">No trades this run.</p>
            ) : (
              <ul className="space-y-1">
                {data?.recent_trades?.slice(0, 8).map((t, i) => (
                  <li key={i} className="flex items-center gap-2 text-[10px] text-slate-300">
                    <TickerSymbol symbol={t.symbol} size="sm" />
                    <span>
                      {t.side} · {t.status}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </GlassPanel>
        </div>
      ) : null}

      <p className="text-[9px] text-slate-600">
        Updated {data?.generated_at_utc?.slice(0, 19) ?? "—"} ·{" "}
        <a href="/diagnostics" className="text-hive-cyan/80 hover:underline">
          Diagnostics bundle
        </a>{" "}
        ·{" "}
        <a href="/paper-candidates" className="text-hive-cyan/80 hover:underline">
          Paper candidates
        </a>{" "}
      </p>
    </div>
  );
}
