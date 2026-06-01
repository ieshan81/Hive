"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, Database, FileArchive, FlaskConical, RefreshCw, Shield, TrendingUp, Wallet, Zap } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { WhyNoTradeCard } from "@/components/panels/WhyNoTradeCard";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type Blocker = { code?: string; count?: number; label?: string };
type Candidate = Record<string, unknown> & { symbol?: string };

type MissionControlStatus = {
  status?: string;
  generated_at_utc?: string;
  freshness?: {
    snapshot_age_seconds?: number | null;
    stale?: boolean;
    degraded?: boolean;
    warnings?: string[];
  };
  account?: Record<string, unknown>;
  paper_execution?: Record<string, unknown>;
  universe?: {
    last_scan_at?: string | null;
    stale_reason?: string | null;
    funnel?: Record<string, number>;
    top_blockers?: Blocker[];
    top_candidates?: Candidate[];
  };
  why_no_trade_summary?: {
    plain?: string | null;
    top_blockers?: Blocker[];
  };
  push_pull?: Record<string, unknown>;
  memory?: Record<string, unknown>;
  diagnostics?: Record<string, unknown>;
  worker?: Record<string, unknown>;
  research_os?: Record<string, unknown>;
  alpha_factory?: Record<string, unknown>;
  latest_order_summary?: Record<string, unknown>;
  next_recommended_operator_action?: string;
  system_warnings?: string[];
};

function numberValue(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function money(value: unknown): string {
  const n = numberValue(value);
  return n === null ? "-" : `$${n.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
}

function label(value: unknown): string {
  return String(value ?? "-").replace(/_/g, " ");
}

function age(value: unknown): string {
  const n = numberValue(value);
  if (n === null) return "unknown age";
  if (n < 60) return `${Math.round(n)}s old`;
  if (n < 3600) return `${Math.round(n / 60)}m old`;
  return `${Math.round(n / 3600)}h old`;
}

function shortTime(value: unknown): string {
  if (!value) return "-";
  return String(value).replace("T", " ").replace("Z", "").slice(0, 19);
}

function Stat({ labelText, value, tone }: { labelText: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{labelText}</p>
      <p className={`mt-1 text-lg font-semibold ${tone ?? "text-white"}`}>{value}</p>
    </div>
  );
}

export function MissionControlPanel() {
  const [data, setData] = useState<MissionControlStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await apiGet<MissionControlStatus>("/api/mission-control/status", { timeoutMs: 5000 });
    if (res.ok && res.data) {
      setData(res.data);
      setError(null);
    } else {
      setError(res.error || `Mission Control unavailable (${res.status})`);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  async function runAction(key: string, endpoint: string, body: Record<string, unknown> = {}) {
    setBusy(key);
    setActionMsg(null);
    const res = await apiPostOperator<Record<string, unknown>>(endpoint, { operator: "mission_control", ...body }, { timeoutMs: 120000 });
    setActionMsg(res.ok ? `${label(key)} started.` : res.error || `${label(key)} failed.`);
    setBusy(null);
    await load();
  }

  const account = data?.account ?? {};
  const safety = data?.paper_execution ?? {};
  const universe = data?.universe ?? {};
  const funnel = universe.funnel ?? {};
  const diagnostics = data?.diagnostics ?? {};
  const researchOs = data?.research_os ?? {};
  const alphaFactory = data?.alpha_factory ?? {};
  const memory = data?.memory ?? {};
  const pushPull = data?.push_pull ?? {};
  const latestOrder = (data?.latest_order_summary?.latest_order ?? null) as Record<string, unknown> | null;
  const topCandidate = useMemo(() => (universe.top_candidates ?? [])[0] ?? null, [universe.top_candidates]);
  const warnings = [...(data?.freshness?.warnings ?? []), ...(data?.system_warnings ?? [])].filter(Boolean);
  const degraded = data?.status === "degraded" || data?.freshness?.degraded;

  if (loading) return <EmptyState message="Loading Mission Control..." className="min-h-[260px]" />;

  return (
    <section className="max-w-6xl space-y-4">
      <header className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] uppercase tracking-wide text-hive-cyan">Mission Control</p>
            <h1 className="mt-1 text-2xl font-semibold text-white">Product Truth</h1>
            <p className="mt-1 text-sm text-slate-400">
              One cached read model for dashboard state. Heavy refreshes run only through operator actions.
            </p>
            <p className="mt-2 text-[11px] text-slate-500">
              Snapshot: {shortTime(data?.generated_at_utc)} · {age(data?.freshness?.snapshot_age_seconds)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="rounded border border-emerald-300/25 bg-emerald-300/10 px-3 py-1 text-xs text-emerald-200">
              Live locked
            </span>
            <span className={safety.paper_broker ? "rounded border border-emerald-300/25 bg-emerald-300/10 px-3 py-1 text-xs text-emerald-200" : "rounded border border-amber-300/25 bg-amber-300/10 px-3 py-1 text-xs text-amber-200"}>
              Paper broker {safety.paper_broker ? "yes" : "check"}
            </span>
            <span className={degraded ? "rounded border border-amber-300/25 bg-amber-300/10 px-3 py-1 text-xs text-amber-200" : "rounded border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-slate-300"}>
              {degraded ? "Degraded" : "Stable"}
            </span>
          </div>
        </div>
        {error ? <p className="mt-3 text-sm text-amber-300">{error}</p> : null}
        {warnings.length > 0 ? (
          <div className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/10 p-3 text-xs text-amber-100">
            <p className="mb-1 flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" /> Subsystem warnings</p>
            <ul className="space-y-0.5">
              {warnings.slice(0, 5).map((w) => <li key={w}>{w}</li>)}
            </ul>
          </div>
        ) : null}
      </header>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Stat labelText="Equity" value={money(account.equity)} />
        <Stat labelText="Cash" value={money(account.cash)} />
        <Stat labelText="Buying Power" value={money(account.buying_power)} />
        <Stat labelText="Open P/L" value={money(account.open_pl)} tone={Number(account.open_pl ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassPanel title="Execution safety" icon={<Shield className="h-4 w-4" />}>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <Stat labelText="Paper orders" value={safety.paper_orders_enabled ? "Enabled" : "Disabled"} tone={safety.paper_orders_enabled ? "text-emerald-300" : "text-amber-300"} />
            <Stat labelText="Can place now" value={safety.can_place_paper_orders_now ? "Yes" : "No"} tone={safety.can_place_paper_orders_now ? "text-emerald-300" : "text-amber-300"} />
            <Stat labelText="Paper learning" value={safety.paper_learning_on ? "On" : "Off"} />
            <Stat labelText="Scheduler" value={safety.scheduler_enabled ? "On" : "Off"} />
          </div>
          {(safety.blockers as string[] | undefined)?.length ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {(safety.blockers as string[]).slice(0, 6).map((b) => (
                <span key={b} className="rounded border border-amber-300/20 bg-amber-300/10 px-2 py-1 text-[11px] text-amber-200">
                  {b}
                </span>
              ))}
            </div>
          ) : null}
        </GlassPanel>

        <GlassPanel title="Universe funnel" icon={<Database className="h-4 w-4" />}>
          <div className="grid grid-cols-3 gap-2">
            {[
              ["Available", funnel.available],
              ["Cached", funnel.cached],
              ["Fresh", funnel.fresh],
              ["Scored", funnel.scored],
              ["Eligible", funnel.eligible],
              ["Shortlist", funnel.shortlisted],
            ].map(([k, v]) => <Stat key={String(k)} labelText={String(k)} value={String(v ?? 0)} />)}
          </div>
          <p className="mt-3 text-[11px] text-slate-500">
            Last scan: {shortTime(universe.last_scan_at)}. {universe.stale_reason ?? "Using latest persisted scan result."}
          </p>
        </GlassPanel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <WhyNoTradeCard
          plain={data?.why_no_trade_summary?.plain}
          topBlockers={universe.top_blockers ?? data?.why_no_trade_summary?.top_blockers ?? []}
          topCandidate={topCandidate}
          shortlisted={funnel.shortlisted ?? 0}
          eligible={funnel.eligible ?? 0}
          canPlacePaperOrders={Boolean(safety.can_place_paper_orders_now)}
          pushPullStatus={String(pushPull.last_result ?? pushPull.status ?? "")}
        />

        <GlassPanel title="Push-pull engine" icon={<Zap className="h-4 w-4" />}>
          <p className="text-sm text-white">{label(pushPull.last_result ?? pushPull.status)}</p>
          <p className="mt-1 text-xs text-slate-400">{String(pushPull.plain_summary ?? "No latest tick summary persisted yet.")}</p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Stat labelText="Last tick" value={shortTime(pushPull.last_tick_at)} />
            <Stat labelText="Data stale" value={pushPull.data_stale ? "Yes" : "No"} tone={pushPull.data_stale ? "text-amber-300" : "text-emerald-300"} />
          </div>
        </GlassPanel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <GlassPanel title="Alpha Factory" icon={<FlaskConical className="h-4 w-4" />}>
          <div className="grid grid-cols-3 gap-2">
            <Stat labelText="Paper" value={alphaFactory.can_trade_paper_now ? "Ready" : "Blocked"} tone={alphaFactory.can_trade_paper_now ? "text-emerald-300" : "text-amber-300"} />
            <Stat labelText="Candidates" value={String(alphaFactory.paper_candidate_count ?? 0)} />
            <Stat labelText="Rejected" value={String(alphaFactory.rejected_strategy_count ?? 0)} />
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            {String(alphaFactory.plain_english ?? "No alpha scorecards yet. Research cycle must create evidence before paper entry.")}
          </p>
        </GlassPanel>

        <GlassPanel title="Research OS" icon={<FlaskConical className="h-4 w-4" />}>
          <div className="grid grid-cols-3 gap-2">
            <Stat labelText="Jobs" value={String(researchOs.research_jobs_running ?? 0)} />
            <Stat labelText="Code" value={String(researchOs.code_proposal_pending_count ?? 0)} />
            <Stat labelText="Live" value={String((researchOs.live_readiness_status as Record<string, unknown> | undefined)?.latest_status ?? "locked")} tone="text-emerald-300" />
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            Latest backtest: {String((researchOs.latest_backtest as Record<string, unknown> | undefined)?.status ?? "none")}.{" "}
            Next: {String(researchOs.next_research_action ?? "Run a research backtest.")}
          </p>
        </GlassPanel>

        <GlassPanel title="Latest execution" icon={<Activity className="h-4 w-4" />}>
          {latestOrder ? (
            <div className="text-xs text-slate-300">
              <p className="text-white">{String(latestOrder.symbol)} · {label(latestOrder.side)} · {label(latestOrder.status)}</p>
              <p className="mt-1 text-slate-500">{shortTime(latestOrder.submitted_at)}</p>
            </div>
          ) : (
            <p className="text-xs text-slate-500">No paper order record yet.</p>
          )}
        </GlassPanel>

        <GlassPanel title="Hive memory" icon={<TrendingUp className="h-4 w-4" />}>
          <div className="grid grid-cols-3 gap-2">
            <Stat labelText="Active" value={String(memory.active_lessons ?? 0)} />
            <Stat labelText="Validated" value={String(memory.validated_lessons ?? 0)} />
            <Stat labelText="Consolidated" value={String(memory.consolidated_lessons ?? 0)} />
          </div>
          <p className="mt-2 text-[11px] text-slate-500">{String((memory.latest_lesson as Record<string, unknown> | undefined)?.summary ?? "No latest lesson.")}</p>
        </GlassPanel>

        <GlassPanel title="Diagnostics" icon={<FileArchive className="h-4 w-4" />}>
          <p className="text-sm text-white">{label(diagnostics.status)}</p>
          <p className="mt-1 text-xs text-slate-400">
            Last completed: {shortTime((diagnostics.last_completed as Record<string, unknown> | null)?.completed_at)}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Running: {diagnostics.export_in_progress ? "yes" : "no"}
          </p>
        </GlassPanel>
      </div>

      <GlassPanel title="Operator actions" icon={<RefreshCw className="h-4 w-4" />}>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy !== null} onClick={() => runAction("refresh market data", "/api/market-data/refresh-bars", { asset_type: "crypto", timeframe: "5Min" })} className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white disabled:opacity-50">
            Refresh market data
          </button>
          <button type="button" disabled={busy !== null} onClick={() => runAction("run universe scan", "/api/universe/refresh")} className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white disabled:opacity-50">
            Run universe scan
          </button>
          <button type="button" disabled={busy !== null} onClick={() => runAction("run paper learning cycle", "/api/autonomous-paper-learning/run-one-cycle")} className="rounded-lg border border-hive-cyan/30 bg-hive-cyan/10 px-3 py-2 text-xs text-hive-cyan disabled:opacity-50">
            Run paper-learning cycle
          </button>
          <button type="button" disabled={busy !== null} onClick={() => runAction("start diagnostic export", "/api/diagnostics/export/run")} className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white disabled:opacity-50">
            Start diagnostic export
          </button>
        </div>
        <p className="mt-3 text-xs text-slate-400">
          Recommended next action: {data?.next_recommended_operator_action ?? "Wait for next tick."}
        </p>
        {busy ? <p className="mt-2 text-xs text-hive-cyan">Running {label(busy)}...</p> : null}
        {actionMsg ? <p className="mt-2 text-xs text-slate-300">{actionMsg}</p> : null}
      </GlassPanel>

      <div className="flex items-center gap-2 text-[11px] text-emerald-400/80">
        <Wallet className="h-3.5 w-3.5" />
        Paper only. Live trading remains locked. Dashboard reads do not run scans, provider calls, Gemini, or orders.
      </div>
    </section>
  );
}
