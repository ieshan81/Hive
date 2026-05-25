"use client";

import { useCallback, useEffect, useState } from "react";
import { Zap } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPost } from "@/lib/apiClient";

export function FastTrainingPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [exitOnly, setExitOnly] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [ft, eo] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/fast-training/status"),
      apiGet<Record<string, unknown>>("/api/fast-training/exit-only/status"),
    ]);
    if (ft.ok) setStatus(ft.data);
    if (eo.ok) setExitOnly(eo.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function act(path: string, label: string) {
    setBusy(true);
    const r = await apiPost(path, { operator: "ui" });
    setMsg(r.ok ? `${label}: ok` : `${label}: ${r.error}`);
    await load();
    setBusy(false);
  }

  return (
    <GlassPanel title="Fast Training" icon={<Zap className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-2">
        Caged path only: TrainingExecutionService → PaperExecutionService. No background loop on Railway.
      </p>
      {status && (
        <p className="text-[9px] font-mono text-slate-400 mb-2">
          loop={String(status.fast_training_loop_enabled)} mode={String(status.mode_enabled)} orders=
          {String(status.orders_total)} live={String(status.live_lock_status)} entries_eligible=
          {String(status.entries_eligible)} entries_allowed={String(status.entries_allowed)}
        </p>
      )}
      {status?.broker_reconciliation != null ? (
        <p className="text-[9px] font-mono text-amber-400/90 mb-2">
          DOGE: {String((status.broker_reconciliation as Record<string, unknown>).classification)} ·{" "}
          {String((status.broker_reconciliation as Record<string, unknown>).reconciliation_state)}
        </p>
      ) : null}
      {exitOnly && (
        <p className="text-[9px] font-mono text-cyan-400/80 mb-2">
          exit_only={String(exitOnly.exit_only_enabled)} open={String(exitOnly.open_positions)} entries=
          {String(exitOnly.entries_allowed)}
        </p>
      )}
      <div className="flex flex-wrap gap-1">
        {[
          ["/api/fast-training/run-once", "Run once"],
          ["/api/fast-training/monitor-exits", "Monitor exits"],
          ["/api/fast-training/enable", "Enable training"],
          ["/api/fast-training/disable", "Disable training"],
          ["/api/fast-training/exit-only/enable", "Exit-only enable"],
          ["/api/fast-training/exit-only/run", "Exit-only run"],
          ["/api/fast-training/exit-only/disable", "Exit-only disable"],
        ].map(([path, label]) => (
          <button
            key={path}
            type="button"
            disabled={busy}
            onClick={() => act(path, label)}
            className="text-[9px] border border-white/10 rounded px-2 py-1 text-slate-300 hover:border-hive-cyan/40"
          >
            {label}
          </button>
        ))}
      </div>
      {msg && <p className="text-[10px] text-slate-500 mt-2 font-mono">{msg}</p>}
    </GlassPanel>
  );
}
