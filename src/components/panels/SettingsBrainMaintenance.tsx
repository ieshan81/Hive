"use client";

import { useEffect, useState } from "react";
import { Brain, RefreshCw, Shield } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPost, apiPostOperator, checkServerOperatorProxy } from "@/lib/apiClient";
import { OperatorAuthPanel } from "@/components/panels/OperatorAuthPanel";

const DANGEROUS = new Set([
  "/api/fast-training/disable",
  "/api/fast-training/exit-only/disable",
  "/api/settings/clear-ghost-rows",
  "/api/memory/consolidation/archive-raw",
]);

export function SettingsBrainMaintenance() {
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tripwire, setTripwire] = useState<Record<string, unknown> | null>(null);
  const [proxy, setProxy] = useState(false);

  useEffect(() => {
    loadTripwire();
    checkServerOperatorProxy().then(setProxy);
  }, []);

  async function loadTripwire() {
    const r = await apiGet<Record<string, unknown>>("/api/settings/live-lock-tripwire");
    if (r.ok) setTripwire(r.data || null);
  }

  async function act(path: string, label: string, confirm?: string) {
    if (confirm && !window.confirm(confirm)) return;
    setBusy(true);
    const useOperator = DANGEROUS.has(path) || path.includes("fast-training") || path.includes("exit-only");
    const r = useOperator
      ? await apiPostOperator(path, { actor: "operator" })
      : await apiPost(path, { actor: "operator" });
    const detail = (r.data as { message?: string })?.message;
    setMsg(r.ok ? `${label}: ${detail || "ok"}` : `${label}: ${r.error}`);
    await loadTripwire();
    setBusy(false);
  }

  const tripOk = tripwire?.tripwire_ok === true;
  const liveLocked = tripwire?.live_lock_status === "locked";

  return (
    <section className="space-y-4 max-w-2xl">
      <p className="text-xs text-slate-400 leading-relaxed">
        Settings are grouped by risk. Read-only checks never place trades. Paper training and exit-only
        only affect the Alpaca paper account. Live trading stays locked unless you deliberately change
        production secrets (not available here).
      </p>

      <OperatorAuthPanel />

      <GlassPanel title="Read-only status checks" icon={<Shield className="h-4 w-4" />}>
        <p className="text-[10px] text-slate-500 mb-2">
          These buttons only refresh status or re-sync broker truth. They do not enable training and do not
          place orders.
        </p>
        <ul className="text-[11px] text-slate-300 space-y-1">
          <li>Live trading: {liveLocked ? "LOCKED" : "CHECK"}</li>
          <li>Paper broker: {tripwire?.paper_broker ? "yes" : "no"}</li>
          <li>Tripwire: {tripOk ? "secure" : "needs review"}</li>
          <li>Server operator proxy: {proxy ? "configured" : "not configured — set OPERATOR_SECRET on frontend service"}</li>
        </ul>
        <button
          type="button"
          className="mt-2 text-[10px] text-hive-cyan flex items-center gap-1"
          onClick={() => loadTripwire()}
        >
          <RefreshCw className="h-3 w-3" /> Refresh tripwire
        </button>
      </GlassPanel>

      <GlassPanel title="Paper training controls" icon={<Brain className="h-4 w-4" />}>
        <p className="text-[10px] text-slate-500 mb-2">
          Paper training lets the bot place Alpaca paper orders only (not live money). Requires operator
          authorization. Use Run Once on the Fast Training page for a single controlled cycle — no background
          loop on Railway.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              act(
                "/api/fast-training/enable",
                "Enable training",
                "Enable Training Mode? The bot may place paper orders when you run once. Live trading stays locked."
              )
            }
            className="text-[10px] border border-hive-cyan/30 text-hive-cyan rounded px-2 py-1"
          >
            Enable paper training
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              act("/api/fast-training/disable", "Disable training", "Disable Training Mode?")
            }
            className="text-[10px] border border-white/10 rounded px-2 py-1"
          >
            Disable training
          </button>
        </div>
      </GlassPanel>

      <GlassPanel title="Exit-only controls">
        <p className="text-[10px] text-slate-500 mb-2">
          Exit-only can close existing paper positions only. It cannot open new buys. Requires operator
          authorization and confirmation.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              act(
                "/api/fast-training/exit-only/disable",
                "Disable exit-only",
                "Disable exit-only mode?"
              )
            }
            className="text-[10px] border border-white/10 rounded px-2 py-1"
          >
            Disable exit-only
          </button>
        </div>
      </GlassPanel>

      <GlassPanel title="Brain maintenance">
        <p className="text-[10px] text-slate-500 mb-2">
          Memory consolidation and graph rebuild update learning data only. They do not submit broker
          orders.
        </p>
        <div className="flex flex-wrap gap-2">
          {[
            ["/api/settings/clear-ui-cache", "Clear UI cache", undefined],
            ["/api/settings/resync-broker-truth", "Re-sync broker truth", undefined],
            ["/api/memory/consolidation/run", "Consolidate memories", undefined],
            ["/api/memory/graph/rebuild", "Rebuild graph", undefined],
          ].map(([path, label, confirm]) => (
            <button
              key={path}
              type="button"
              disabled={busy}
              onClick={() => act(String(path), String(label), confirm)}
              className="text-[10px] border border-white/10 rounded px-2 py-1"
            >
              {label}
            </button>
          ))}
        </div>
      </GlassPanel>

      <GlassPanel title="Danger zone">
        <p className="text-[10px] text-amber-400/90 mb-2">
          These change stored database rows. Operator authorization and confirmation are required. They do
          not enable live trading.
        </p>
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            act(
              "/api/settings/clear-ghost-rows",
              "Clear ghost rows",
              "Remove stale zero-qty rows not on broker?"
            )
          }
          className="text-[10px] border border-red-500/30 text-red-300 rounded px-2 py-1"
        >
          Clear ghost rows
        </button>
      </GlassPanel>

      {msg && <p className="text-[11px] text-slate-400">{msg}</p>}
    </section>
  );
}
