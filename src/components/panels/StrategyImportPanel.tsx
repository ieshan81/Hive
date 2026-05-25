"use client";

import { useCallback, useEffect, useState } from "react";
import { FileCode } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPost } from "@/lib/apiClient";

export function StrategyImportPanel() {
  const [list, setList] = useState<Record<string, unknown>[]>([]);
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [manifest, setManifest] = useState(
    '{"strategy_id":"sandbox_test","name":"Sandbox Test","symbols":["DOGE/USD"]}'
  );
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [st, imp] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/strategies/import/status"),
      apiGet<{ strategies?: Record<string, unknown>[] }>("/api/strategies/imported"),
    ]);
    if (st.ok) setStatus(st.data);
    if (imp.ok && imp.data?.strategies) setList(imp.data.strategies);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function doImport() {
    try {
      const parsed = JSON.parse(manifest);
      const r = await apiPost("/api/strategies/import", { manifest: parsed });
      setMsg(r.ok ? `Imported: ${JSON.stringify(r.data)}` : r.error || "failed");
      await load();
    } catch (e) {
      setMsg(String(e));
    }
  }

  return (
    <GlassPanel title="Strategy Import (Sandbox)" icon={<FileCode className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-2">
        Manifest + AST only. No broker, env, subprocess, or network. Backtest-only lifecycle.
      </p>
      {status && (
        <p className="text-[9px] font-mono text-slate-500 mb-2">
          sandbox={String(status.sandbox)} broker={String(status.broker_access)} imported=
          {String(status.imported_count)}
        </p>
      )}
      <textarea
        value={manifest}
        onChange={(e) => setManifest(e.target.value)}
        className="w-full h-16 text-[9px] font-mono bg-black/40 border border-white/10 rounded p-2 mb-2"
      />
      <button type="button" onClick={doImport} className="text-[10px] text-hive-cyan mb-2">
        Import manifest
      </button>
      <ul className="text-[9px] text-slate-400 space-y-1 max-h-[120px] overflow-y-auto">
        {list.map((s) => (
          <li key={String(s.strategy_id)}>
            {String(s.strategy_id)} · {String(s.current_stage)}
          </li>
        ))}
      </ul>
      {msg && <p className="text-[10px] font-mono text-slate-500 mt-1">{msg}</p>}
    </GlassPanel>
  );
}
