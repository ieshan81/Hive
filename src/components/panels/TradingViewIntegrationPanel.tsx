"use client";

import { useCallback, useEffect, useState } from "react";
import { LineChart } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

type TradingViewStatus = {
  mode?: string;
  execution_allowed?: boolean;
  execution_blocked_reason?: string;
  latest_event?: Record<string, unknown> | null;
};

export function TradingViewIntegrationPanel() {
  const [status, setStatus] = useState<TradingViewStatus | null>(null);
  const [overlays, setOverlays] = useState<Record<string, unknown>[]>([]);

  const load = useCallback(async () => {
    const [st, ov] = await Promise.all([
      apiGet<TradingViewStatus>("/api/tradingview/status"),
      apiGet<{ overlays?: Record<string, unknown>[] }>("/api/tradingview/overlays"),
    ]);
    if (st.ok) setStatus(st.data);
    if (ov.ok) setOverlays(ov.data?.overlays || []);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <GlassPanel title="TradingView Wrapper" icon={<LineChart className="h-4 w-4" />}>
      <p className="mb-3 text-[10px] text-slate-500">
        Display-only overlays for signals, levels, memory notes, and blockers. TradingView cannot place orders.
      </p>
      <div className="grid grid-cols-3 gap-2 text-[10px]">
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Mode</p>
          <p className="text-slate-200">{status?.mode ?? "display_only"}</p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Execution</p>
          <p className="text-emerald-300">{status?.execution_allowed ? "Unexpected" : "Blocked"}</p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Events</p>
          <p className="text-slate-200">{overlays.length}</p>
        </div>
      </div>
      <p className="mt-2 text-[10px] text-slate-500">
        Block reason: {status?.execution_blocked_reason ?? "display_only_execution_blocked"}
      </p>
      <ul className="mt-3 max-h-56 space-y-2 overflow-auto text-[10px] text-slate-400">
        {!overlays.length ? <li>No TradingView events yet.</li> : null}
        {overlays.slice(0, 12).map((o, i) => (
          <li key={String(o.id ?? i)} className="rounded border border-white/10 p-2">
            {String(o.event_type ?? "signal")} - {String((o.mapped_signal as Record<string, unknown> | undefined)?.symbol ?? "unknown")}
            <p className="text-slate-500">{String(o.execution_blocked_reason ?? "display_only_execution_blocked")}</p>
          </li>
        ))}
      </ul>
    </GlassPanel>
  );
}

