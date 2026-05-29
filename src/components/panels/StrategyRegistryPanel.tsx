"use client";

import { useCallback, useEffect, useState } from "react";
import { Shield, RefreshCw, Layers, AlertTriangle } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type RegistryRow = Record<string, unknown>;
type Snapshot = {
  live_locked?: boolean;
  live_trading_enabled?: boolean;
  paper_trading_only?: boolean;
  counts?: Record<string, number>;
};

export function StrategyRegistryPanel() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [all, setAll] = useState<RegistryRow[]>([]);
  const [active, setActive] = useState<RegistryRow[]>([]);
  const [candidates, setCandidates] = useState<RegistryRow[]>([]);
  const [rejected, setRejected] = useState<RegistryRow[]>([]);
  const [selected, setSelected] = useState<RegistryRow | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [paperLearn, setPaperLearn] = useState<Record<string, unknown> | null>(null);
  const [experimentEligible, setExperimentEligible] = useState<RegistryRow[]>([]);

  const load = useCallback(async () => {
    const [reg, act, cand, rej, plStatus, plEligible] = await Promise.all([
      apiGet<{ strategies?: RegistryRow[] }>("/api/strategies/registry"),
      apiGet<{ strategies?: RegistryRow[] }>("/api/strategies/active"),
      apiGet<{ strategies?: RegistryRow[] }>("/api/strategies/paper-candidates"),
      apiGet<{ strategies?: RegistryRow[] }>("/api/strategies/rejected"),
      apiGet<Record<string, unknown>>("/api/paper-learning/status"),
      apiGet<{ eligible?: RegistryRow[] }>("/api/paper-learning/eligible-strategies"),
    ]);
    setPaperLearn(plStatus.data || null);
    setExperimentEligible(plEligible.data?.eligible || []);
    const rows = reg.data?.strategies || [];
    setAll(rows);
    setActive(act.data?.strategies || []);
    setCandidates(cand.data?.strategies || []);
    setRejected(rej.data?.strategies || []);
    setSnapshot({
      live_locked: true,
      live_trading_enabled: false,
      paper_trading_only: true,
      counts: {
        total: rows.length,
        active: (act.data?.strategies || []).length,
        paper_candidates: (cand.data?.strategies || []).length,
        rejected: (rej.data?.strategies || []).length,
        watchlist: rows.filter((r) => r.current_stage === "watchlist").length,
        stale_warnings: 0,
      },
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function syncAndValidate() {
    setBusy(true);
    await apiPostOperator("/api/strategies/registry/sync-from-lab", {});
    await apiPostOperator("/api/strategies/memories/validate", {});
    await apiPostOperator("/api/strategies/validate", { actor: "operator" });
    await apiPostOperator("/api/strategies/promote-candidates", { actor: "operator" });
    setMsg("Registry synced and validation gate run");
    await load();
    setBusy(false);
  }

  async function openDetail(row: RegistryRow) {
    const sid = String(row.strategy_id);
    const [sc, lc, mem] = await Promise.all([
      apiGet(`/api/strategies/${encodeURIComponent(sid)}/scorecard`),
      apiGet(`/api/strategies/${encodeURIComponent(sid)}/lifecycle`),
      apiGet(`/api/strategies/${encodeURIComponent(sid)}/memories`),
    ]);
    setSelected(row);
    setDetail({
      scorecard: sc.data,
      lifecycle: lc.data,
      memories: mem.data,
    });
  }

  const researchOnly = all.filter((r) =>
    ["research_only", "watchlist"].includes(String(r.current_stage))
  );

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Layers className="h-5 w-5 text-hive-cyan" />
          <h2 className="text-lg font-semibold text-white">Living Strategy Registry</h2>
        </div>
        <button
          type="button"
          onClick={syncAndValidate}
          disabled={busy}
          className="text-xs border border-hive-cyan/40 text-hive-cyan rounded px-2 py-1 flex items-center gap-1"
        >
          <RefreshCw className="h-3 w-3" /> Sync & validate
        </button>
      </header>

      {msg && <p className="text-[10px] text-slate-500 font-mono">{msg}</p>}

      <GlassPanel title="Aggressive Paper Learning">
        <div className="flex flex-wrap gap-2 text-xs mb-2">
          <span className={paperLearn?.mode_enabled ? "text-amber-300" : "text-slate-400"}>
            Mode: {paperLearn?.mode_enabled ? "ENABLED" : "disabled"}
          </span>
          <span className="text-slate-500">Experimental paper only · Not live eligible · Learning mode</span>
        </div>
        <p className="text-[10px] text-slate-500 mb-2">
          Decisions today: {String(paperLearn?.decisions_today ?? 0)} · Eligible experiments:{" "}
          {experimentEligible.length}
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy}
            className="text-[10px] border border-amber-500/40 text-amber-300 rounded px-2 py-0.5"
            onClick={async () => {
              setBusy(true);
              await apiPostOperator("/api/paper-learning/enable", { operator: "operator" });
              setMsg("Paper learning enabled (caged — no live)");
              await load();
              setBusy(false);
            }}
          >
            Enable learning
          </button>
          <button
            type="button"
            disabled={busy}
            className="text-[10px] border border-white/10 text-slate-400 rounded px-2 py-0.5"
            onClick={async () => {
              setBusy(true);
              await apiPostOperator("/api/paper-learning/disable", { operator: "operator" });
              setMsg("Paper learning disabled");
              await load();
              setBusy(false);
            }}
          >
            Disable
          </button>
          <button
            type="button"
            disabled={busy}
            className="text-[10px] border border-hive-cyan/30 text-hive-cyan rounded px-2 py-0.5"
            onClick={async () => {
              setBusy(true);
              await apiPostOperator("/api/strategies/experiment-eligibility/scan", {});
              await load();
              setBusy(false);
            }}
          >
            Scan eligibility
          </button>
        </div>
        {experimentEligible.length > 0 && (
          <ul className="mt-2 text-[10px] text-slate-400 max-h-24 overflow-auto">
            {experimentEligible.slice(0, 8).map((e) => (
              <li key={String(e.strategy_id)}>
                {String(e.strategy_id)} — {String(e.reason || "eligible")}
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>

      <GlassPanel title="System Strategy Banner">
        <div className="flex flex-wrap gap-3 text-xs">
          <span className="text-red-300 flex items-center gap-1">
            <Shield className="h-3 w-3" /> Live trading: LOCKED
          </span>
          <span className="text-emerald-300">Paper: enabled (runtime)</span>
          <span className="text-slate-400">Active: {snapshot?.counts?.active ?? 0}</span>
          <span className="text-slate-400">Candidates: {snapshot?.counts?.paper_candidates ?? 0}</span>
          <span className="text-amber-400">Rejected: {snapshot?.counts?.rejected ?? 0}</span>
        </div>
      </GlassPanel>

      <StrategyTable title="Active / Paper Active" rows={active} onSelect={openDetail} />
      <StrategyTable title="Paper Candidates / Promotion Queue" rows={candidates} onSelect={openDetail} showPromo />
      <StrategyTable title="Watchlist / Research Only" rows={researchOnly} onSelect={openDetail} />
      <details className="rounded-lg border border-white/5 p-3">
        <summary className="text-xs text-slate-400 cursor-pointer">Rejected / Retired ({rejected.length})</summary>
        <StrategyTable title="" rows={rejected} onSelect={openDetail} compact />
      </details>

      {selected && detail && (
        <GlassPanel title={`Strategy: ${String(selected.strategy_id)}`}>
          <p className="text-xs text-slate-400 mb-2">
            Stage: <span className="text-white">{String(selected.current_stage)}</span> · Score:{" "}
            {String(selected.current_score ?? "—")} · Memories: {String(selected.memory_count)} (
            {String(selected.validated_memory_count)} validated, {String(selected.pending_memory_count)} pending)
          </p>
          {Array.isArray((detail.memories as { memories?: unknown[] })?.memories) && (
            <p className="text-[10px] text-violet-300">
              Pending memories do not influence ranking until validated by the deterministic gate.
            </p>
          )}
          <pre className="text-[9px] text-slate-500 max-h-32 overflow-auto mt-2">
            {JSON.stringify(detail.scorecard, null, 2)}
          </pre>
        </GlassPanel>
      )}
    </section>
  );
}

function StrategyTable({
  title,
  rows,
  onSelect,
  showPromo,
  compact,
}: {
  title: string;
  rows: RegistryRow[];
  onSelect: (r: RegistryRow) => void;
  showPromo?: boolean;
  compact?: boolean;
}) {
  if (!rows.length && !compact) {
    return (
      <GlassPanel title={title}>
        <p className="text-xs text-slate-500">No strategies in this stage.</p>
      </GlassPanel>
    );
  }
  if (!rows.length) return null;
  return (
    <GlassPanel title={title}>
      <table className="w-full text-[10px]">
        <thead>
          <tr className="text-slate-500">
            <th className="text-left py-1">Strategy</th>
            <th>Stage</th>
            <th>Score</th>
            <th>Conf</th>
            {!compact && <th>Blockers</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={String(r.strategy_id)}
              className="text-slate-300 border-t border-white/5 cursor-pointer hover:bg-white/5"
              onClick={() => onSelect(r)}
            >
              <td className="py-1 text-white">{String(r.name || r.strategy_id)}</td>
              <td className="text-center">{String(r.current_stage)}</td>
              <td className="text-center">{String(r.current_score ?? "—")}</td>
              <td className="text-center">{String(r.confidence)}</td>
              {!compact && (
                <td className="text-amber-400 text-[9px]">
                  {Array.isArray(r.blockers) && (r.blockers as string[]).length
                    ? (r.blockers as string[]).join(", ")
                    : showPromo
                      ? "awaiting gate"
                      : "—"}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </GlassPanel>
  );
}
