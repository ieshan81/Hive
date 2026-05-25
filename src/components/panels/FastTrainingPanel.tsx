"use client";

import { useCallback, useEffect, useState } from "react";
import { Zap } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator, checkServerOperatorProxy } from "@/lib/apiClient";
import { hasSessionOperatorToken } from "@/lib/operatorAuth";
import { friendlyBlocker } from "@/lib/labels";

export function FastTrainingPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [exitOnly, setExitOnly] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [canMutate, setCanMutate] = useState(false);

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
    Promise.all([checkServerOperatorProxy(), Promise.resolve(hasSessionOperatorToken())]).then(
      ([proxy, session]) => setCanMutate(proxy || session)
    );
  }, [load]);

  async function act(path: string, label: string, confirmMsg?: string) {
    if (!canMutate) {
      setMsg("Operator authorization required — configure server proxy or session token in Settings.");
      return;
    }
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    setBusy(true);
    const r = await apiPostOperator(path, { operator: "ui" });
    setMsg(r.ok ? `${label}: ok` : `${label}: ${r.error ?? r.status}`);
    await load();
    setBusy(false);
  }

  const blockers = (status?.current_blockers_user_friendly as string[]) ?? [];
  const trainingOn = Boolean(status?.training_mode_enabled);

  return (
    <GlassPanel title="Fast Training" icon={<Zap className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Paper training only. No background loop on Railway — use Run Once when you enable training.
      </p>

      <div className="grid grid-cols-2 gap-2 mb-3 text-[10px]">
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Training Mode</div>
          <div className="font-semibold text-slate-200">{trainingOn ? "ON" : "OFF"}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Can open paper trade?</div>
          <div className="font-semibold text-slate-200">
            {status?.entries_allowed ? "YES" : "NO"}
          </div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Signals found</div>
          <div className="font-semibold">{String(status?.entries_eligible ?? false)}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Final permission</div>
          <div className="font-semibold">{String(status?.can_submit_orders ?? false)}</div>
        </div>
      </div>

      {!trainingOn && (
        <p className="text-[11px] text-amber-300/90 mb-2">
          The bot is only watching. It cannot place orders because Training Mode is OFF.
        </p>
      )}

      {status?.plain_message != null ? (
        <p className="text-[10px] text-slate-400 mb-2">{String(status.plain_message)}</p>
      ) : null}

      {Boolean(status?.stale_lease_warning) && (
        <p className="text-[9px] text-slate-500 mb-2 italic">{String(status?.stale_lease_warning)}</p>
      )}

      {blockers.length > 0 && (
        <ul className="text-[9px] text-slate-400 mb-2 list-disc pl-4">
          {blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}

      {exitOnly && (
        <p className="text-[9px] text-cyan-400/80 mb-2">
          Exit-only: {exitOnly.exit_only_enabled ? "ON" : "OFF"} · Open positions:{" "}
          {String(exitOnly.open_positions ?? 0)}
          {Number(exitOnly.open_positions) === 0
            ? " — Nothing to close; broker shows no active position."
            : ""}
        </p>
      )}

      <div className="flex flex-wrap gap-1">
        {[
          [
            "/api/fast-training/run-once",
            "Run once",
            "Run one controlled training cycle? No background loop.",
          ],
          ["/api/fast-training/enable", "Enable training", "Enable Training Mode? Bot may place paper orders."],
          ["/api/fast-training/disable", "Disable training", undefined],
          ["/api/fast-training/exit-only/enable", "Exit-only enable", "Enable exit-only? Can only close positions, not open buys."],
          ["/api/fast-training/exit-only/disable", "Exit-only disable", undefined],
        ].map(([path, label, confirm]) => (
          <button
            key={path}
            type="button"
            disabled={busy || !canMutate}
            title={!canMutate ? "Operator authorization required" : undefined}
            onClick={() => act(String(path), String(label), confirm as string | undefined)}
            className="text-[9px] border border-white/10 rounded px-2 py-1 text-slate-300 hover:border-hive-cyan/40"
          >
            {label}
          </button>
        ))}
      </div>
      {msg && <p className="text-[10px] text-slate-500 mt-2">{msg}</p>}
    </GlassPanel>
  );
}
