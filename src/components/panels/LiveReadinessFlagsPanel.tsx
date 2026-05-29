"use client";

import { useCallback, useEffect, useState } from "react";
import { LockKeyhole } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type LiveFlagStatus = {
  live_locked?: boolean;
  paper_broker?: boolean;
  live_orders_enabled?: boolean;
  live_trading_enabled?: boolean;
  confirmation_phrase_required?: string;
  latest_request?: Record<string, unknown> | null;
};

export function LiveReadinessFlagsPanel() {
  const [status, setStatus] = useState<LiveFlagStatus | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const r = await apiGet<LiveFlagStatus>("/api/live-flags/status");
    if (r.ok) setStatus(r.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function dryRun() {
    setBusy(true);
    const r = await apiPostOperator("/api/live-flags/dry-run", {
      actor_type: "operator",
      requested_flags: { live_trading_enabled: true },
      confirmation_phrase: "",
    });
    const blockers = (r.data as { blockers?: string[] } | null)?.blockers || [];
    setMsg(r.ok ? `Dry run blocked: ${blockers.join(", ")}` : r.error || String(r.status));
    setBusy(false);
  }

  return (
    <GlassPanel title="Live Readiness / Flags" icon={<LockKeyhole className="h-4 w-4" />}>
      <p className="mb-3 text-[10px] text-amber-300">
        Live architecture is ledgered for future review. This build does not unlock live trading.
      </p>
      <div className="grid grid-cols-2 gap-2 text-[10px]">
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Live locked</p>
          <p className="text-emerald-300">{status?.live_locked !== false ? "Yes" : "Check"}</p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Paper broker</p>
          <p className={status?.paper_broker ? "text-emerald-300" : "text-amber-300"}>
            {status?.paper_broker ? "Yes" : "Unavailable"}
          </p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Live orders</p>
          <p className="text-emerald-300">{status?.live_orders_enabled ? "Unexpected" : "Off"}</p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">AI approval</p>
          <p className="text-emerald-300">Forbidden</p>
        </div>
      </div>
      <button
        type="button"
        disabled={busy}
        onClick={dryRun}
        className="mt-3 rounded border border-white/15 px-2 py-1 text-[10px] text-slate-200 disabled:opacity-50"
      >
        Dry-run live request
      </button>
      {status?.latest_request ? (
        <p className="mt-2 text-[10px] text-slate-500">
          Latest request: {String(status.latest_request.status)} - {String(status.latest_request.rejected_reason ?? "ledgered")}
        </p>
      ) : null}
      {msg ? <p className="mt-2 text-[10px] text-slate-400">{msg}</p> : null}
    </GlassPanel>
  );
}

