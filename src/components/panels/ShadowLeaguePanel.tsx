"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { useRuntimeTruth } from "@/components/layout/RuntimeTruthProvider";
import { apiGet } from "@/lib/apiClient";

type ShadowStatus = {
  status?: string;
  enabled?: boolean;
  ui_state?: string;
  shadow_league_count?: number;
  total_shadow_observations?: number;
  total_shadow_trades?: number;
  crypto_shadow_count?: number;
  stock_shadow_count?: number;
  scheduler_seen?: boolean;
  scheduler_enabled?: boolean;
  last_tick_at?: string | null;
  next_tick_at?: string | null;
  reason_shadow_count_zero?: string | null;
  closest_setup?: { symbol?: string; level_name?: string; missing_evidence?: string[] };
  missing_evidence?: string[];
  counts_as_broker_evidence?: boolean;
  broker_evidence_count?: number;
};

const WAITING_STATES = new Set([
  "enabled_waiting_for_setups",
  "enabled_collecting_observations",
]);

function runtimeShadowFallback(truth: ReturnType<typeof useRuntimeTruth>["truth"]): ShadowStatus | null {
  if (!truth?.shadow_league_enabled) return null;
  return {
    enabled: true,
    ui_state: truth.shadow_ui_state || "enabled_waiting_for_setups",
    shadow_league_count: truth.shadow_count ?? 0,
    scheduler_enabled: truth.scheduler_enabled,
    scheduler_seen: truth.shadow_ui_state !== "disabled_by_config",
    last_tick_at: truth.last_tick_at,
    next_tick_at: truth.next_tick_at,
    reason_shadow_count_zero: truth.reason_shadow_count_zero,
  };
}

export function ShadowLeaguePanel() {
  const { truth } = useRuntimeTruth();
  const [data, setData] = useState<ShadowStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiGet<ShadowStatus>("/api/shadow-league/status", { timeoutMs: 12000 }).then((res) => {
      if (cancelled) return;
      setLoading(false);
      if (res.ok && res.data) {
        setData(res.data);
        setErr(null);
      } else {
        const fallback = runtimeShadowFallback(truth);
        if (fallback) {
          setData(fallback);
          setErr("Detailed shadow status slow — showing runtime summary");
        } else {
          setErr(res.error || "Shadow league unavailable");
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, [truth]);

  const effective = data ?? runtimeShadowFallback(truth);

  if (loading && !effective) {
    return (
      <GlassPanel title="Shadow League">
        <p className="text-sm text-slate-400">Loading shadow league status…</p>
      </GlassPanel>
    );
  }

  if (effective?.enabled === false && effective?.ui_state === "disabled_by_config") {
    return (
      <GlassPanel title="Shadow League">
        <p className="text-sm text-slate-400">Shadow league is disabled in config.</p>
      </GlassPanel>
    );
  }

  if (!effective && err) {
    return (
      <GlassPanel title="Shadow League">
        <p className="text-sm text-amber-300">{err}</p>
      </GlassPanel>
    );
  }

  const closest = effective?.closest_setup;
  const missing = closest?.missing_evidence?.length ? closest.missing_evidence : effective?.missing_evidence ?? [];
  const waiting =
    effective?.enabled !== false &&
    (effective?.shadow_league_count ?? 0) === 0 &&
    (WAITING_STATES.has(effective?.ui_state || "") || truth?.shadow_league_enabled);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <header>
        <h1 className="text-2xl font-bold text-white">Shadow League</h1>
        <p className="mt-1 text-sm text-slate-400">What Hive learns without broker orders</p>
      </header>

      {err ? <p className="text-xs text-amber-400">{err}</p> : null}

      {waiting ? (
        <div className="rounded-xl border border-cyan-500/30 bg-cyan-950/20 px-4 py-3 text-sm text-cyan-100">
          Shadow learning active — waiting for setups (count is zero; scheduler is on).
        </div>
      ) : null}

      {!effective?.scheduler_enabled && effective?.scheduler_enabled !== undefined ? (
        <div className="rounded-xl border-2 border-red-500/50 bg-red-950/30 px-4 py-3 text-sm text-red-200">
          Scheduler OFF — shadow learning needs automatic ticks.{" "}
          <Link href="/mission-control" className="underline">
            Mission Control
          </Link>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Observations", effective?.total_shadow_observations ?? 0],
          ["Shadow trades", effective?.total_shadow_trades ?? effective?.shadow_league_count ?? 0],
          ["Crypto", effective?.crypto_shadow_count ?? 0],
          ["Stock", effective?.stock_shadow_count ?? 0],
        ].map(([label, val]) => (
          <div key={String(label)} className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="text-[10px] uppercase text-slate-500">{label}</p>
            <p className="text-xl font-bold text-white">{val}</p>
          </div>
        ))}
      </div>

      <GlassPanel title="Status">
        <ul className="space-y-2 text-sm text-slate-300">
          <li>
            <span className="text-slate-500">UI state:</span> {effective?.ui_state?.replace(/_/g, " ") ?? "—"}
          </li>
          <li>
            <span className="text-slate-500">Total records:</span> {effective?.shadow_league_count ?? 0}
          </li>
          <li>
            <span className="text-slate-500">Broker evidence:</span>{" "}
            {effective?.broker_evidence_count ?? 0} (shadow never counts)
          </li>
          <li>
            <span className="text-slate-500">Scheduler seen:</span> {effective?.scheduler_seen ? "yes" : "no"}
          </li>
          <li>
            <span className="text-slate-500">Last tick:</span> {effective?.last_tick_at?.slice(0, 19) ?? "—"}
          </li>
          <li>
            <span className="text-slate-500">Next tick:</span> {effective?.next_tick_at?.slice(0, 19) ?? "—"}
          </li>
          {(effective?.shadow_league_count ?? 0) === 0 && effective?.reason_shadow_count_zero ? (
            <li className="text-amber-200/90">
              <span className="text-slate-500">Why zero:</span> {effective.reason_shadow_count_zero.replace(/_/g, " ")}
            </li>
          ) : null}
        </ul>
      </GlassPanel>

      <GlassPanel title="Closest to promotion">
        {closest?.symbol ? (
          <p className="text-sm text-white">
            {closest.symbol}
            {closest.level_name ? (
              <span className="ml-2 text-xs text-slate-500">({closest.level_name})</span>
            ) : null}
          </p>
        ) : (
          <p className="text-sm text-slate-500">No observed setup yet this validation run.</p>
        )}
        {missing.length > 0 ? (
          <p className="mt-2 text-xs text-amber-200/90">Missing evidence: {missing.join(", ")}</p>
        ) : null}
      </GlassPanel>
    </div>
  );
}
