"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { GlassPanel } from "@/components/ui/GlassPanel";
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

export function ShadowLeaguePanel() {
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
        setErr(res.error || "Shadow league unavailable");
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <GlassPanel title="Shadow League">
        <p className="text-sm text-slate-400">Loading shadow league status…</p>
      </GlassPanel>
    );
  }

  if (data?.enabled === false && data?.ui_state === "disabled_by_config") {
    return (
      <GlassPanel title="Shadow League">
        <p className="text-sm text-slate-400">Shadow league is disabled in config.</p>
      </GlassPanel>
    );
  }

  if (!data && err) {
    return (
      <GlassPanel title="Shadow League">
        <p className="text-sm text-amber-300">{err}</p>
      </GlassPanel>
    );
  }

  const closest = data?.closest_setup;
  const missing = closest?.missing_evidence?.length ? closest.missing_evidence : data?.missing_evidence ?? [];
  const waiting = data?.enabled && (data.shadow_league_count ?? 0) === 0 && WAITING_STATES.has(data.ui_state || "");

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <header>
        <h1 className="text-2xl font-bold text-white">Shadow League</h1>
        <p className="mt-1 text-sm text-slate-400">What Hive learns without broker orders</p>
      </header>

      {err ? <p className="text-xs text-amber-400">{err}</p> : null}

      {waiting ? (
        <div className="rounded-xl border border-cyan-500/30 bg-cyan-950/20 px-4 py-3 text-sm text-cyan-100">
          Shadow learning active — no setups met observation floor yet.
        </div>
      ) : null}

      {!data?.scheduler_enabled ? (
        <div className="rounded-xl border-2 border-red-500/50 bg-red-950/30 px-4 py-3 text-sm text-red-200">
          Scheduler OFF — shadow learning needs automatic ticks.{" "}
          <Link href="/mission-control" className="underline">
            Mission Control
          </Link>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Observations", data?.total_shadow_observations ?? 0],
          ["Shadow trades", data?.total_shadow_trades ?? 0],
          ["Crypto", data?.crypto_shadow_count ?? 0],
          ["Stock", data?.stock_shadow_count ?? 0],
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
            <span className="text-slate-500">UI state:</span> {data?.ui_state?.replace(/_/g, " ") ?? "—"}
          </li>
          <li>
            <span className="text-slate-500">Total records:</span> {data?.shadow_league_count ?? 0}
          </li>
          <li>
            <span className="text-slate-500">Broker evidence:</span>{" "}
            {data?.broker_evidence_count ?? 0} (shadow never counts)
          </li>
          <li>
            <span className="text-slate-500">Scheduler seen:</span> {data?.scheduler_seen ? "yes" : "no"}
          </li>
          <li>
            <span className="text-slate-500">Last tick:</span> {data?.last_tick_at?.slice(0, 19) ?? "—"}
          </li>
          <li>
            <span className="text-slate-500">Next tick:</span> {data?.next_tick_at?.slice(0, 19) ?? "—"}
          </li>
          {(data?.shadow_league_count ?? 0) === 0 && data?.reason_shadow_count_zero ? (
            <li className="text-amber-200/90">
              <span className="text-slate-500">Why zero:</span> {data.reason_shadow_count_zero.replace(/_/g, " ")}
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
