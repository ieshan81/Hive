"use client";

import { useState } from "react";
import { Brain, RefreshCw, Shield } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiPost, apiGet } from "@/lib/apiClient";

export function SettingsBrainMaintenance() {
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tripwire, setTripwire] = useState<Record<string, unknown> | null>(null);

  async function loadTripwire() {
    const r = await apiGet<Record<string, unknown>>("/api/settings/live-lock-tripwire");
    if (r.ok) setTripwire(r.data || null);
  }

  async function act(path: string, label: string) {
    setBusy(true);
    const r = await apiPost(path, { actor: "operator" });
    setMsg(r.ok ? `${label}: ok` : `${label}: ${r.error}`);
    await loadTripwire();
    setBusy(false);
  }

  return (
    <GlassPanel title="Hive Brain Maintenance" icon={<Brain className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Training Capital / Aggressive Learning Mode uses caged paper broker only. Audit logs always record real
        broker_mode.
      </p>
      <div className="flex items-center gap-2 text-xs text-red-300 mb-3">
        <Shield className="h-3 w-3" />
        Live trading: LOCKED — cache actions cannot bypass locks
      </div>
      {tripwire && (
        <p className="text-[9px] text-slate-500 font-mono mb-2">
          paper_broker={String(tripwire.paper_broker)} · live_orders=
          {String(tripwire.live_orders_enabled)} · tripwire_ok={String(tripwire.tripwire_ok)}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {[
          ["/api/fast-training/disable", "Disable Fast Training"],
          ["/api/fast-training/exit-only/disable", "Disable Exit-Only"],
          ["/api/settings/clear-ui-cache", "Clear UI Cache"],
          ["/api/settings/resync-broker-truth", "Re-sync Broker Truth"],
          ["/api/settings/clear-ghost-rows", "Clear Ghost Rows"],
          ["/api/memory/consolidation/run", "Consolidate Memories"],
          ["/api/memory/consolidation/archive-raw", "Archive Raw Duplicates"],
          ["/api/memory/graph/rebuild", "Rebuild Hive Graph"],
          ["/api/memory/ai-learning/generate", "Generate AI Lessons"],
          ["/api/settings/export-brain-bundle", "Export Brain Bundle"],
        ].map(([path, label]) => (
          <button
            key={path}
            type="button"
            disabled={busy}
            onClick={() => act(path, label)}
            className="text-[10px] border border-white/10 text-slate-300 rounded px-2 py-1 hover:border-hive-cyan/40"
          >
            {label}
          </button>
        ))}
        <button
          type="button"
          className="text-[10px] text-hive-cyan flex items-center gap-1"
          onClick={() => loadTripwire()}
        >
          <RefreshCw className="h-3 w-3" /> Tripwire
        </button>
      </div>
      {msg && <p className="text-[10px] text-slate-400 mt-2 font-mono">{msg}</p>}
    </GlassPanel>
  );
}
