"use client";

import { useCallback, useEffect, useState } from "react";
import { FileCode } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator, checkServerOperatorProxy } from "@/lib/apiClient";
import { hasSessionOperatorToken } from "@/lib/operatorAuth";
export function StrategyImportPanel() {
  const [list, setList] = useState<Record<string, unknown>[]>([]);
  const [importedMsg, setImportedMsg] = useState<string | null>(null);
  const [manifest, setManifest] = useState(
    '{"strategy_id":"sandbox_test","name":"Sandbox Test","symbols":["DOGE/USD"]}'
  );
  const [msg, setMsg] = useState<string | null>(null);
  const [canImport, setCanImport] = useState(false);

  const load = useCallback(async () => {
    const imp = await apiGet<{
      status?: string;
      imported_count?: number;
      strategies?: Record<string, unknown>[];
      message?: string;
    }>("/api/strategies/imported");
    if (imp.ok && imp.data) {
      setList(imp.data.strategies || []);
      setImportedMsg(imp.data.message || null);
    }
  }, []);

  useEffect(() => {
    load();
    checkServerOperatorProxy().then((p) => setCanImport(p || hasSessionOperatorToken()));
  }, [load]);

  async function doImport() {
    if (!canImport) {
      setMsg("Operator authorization required before import.");
      return;
    }
    if (!window.confirm("Import strategy to sandbox (backtest-only)?")) return;
    try {
      const parsed = JSON.parse(manifest);
      const r = await apiPostOperator("/api/strategies/import", { manifest: parsed });
      if (r.ok && r.data) {
        const d = r.data as { status?: string; strategy_id?: string; stage?: string; message?: string };
        setMsg(
          d.status === "ok"
            ? `Imported ${d.strategy_id || "strategy"} at stage ${d.stage || "unknown"}. Backtest-only — cannot trade.`
            : d.message || "Import failed"
        );
      } else {
        setMsg(r.error || "Import failed");
      }
      await load();
    } catch (e) {
      setMsg(String(e));
    }
  }

  return (
    <GlassPanel title="Strategy import (sandbox)" icon={<FileCode className="h-4 w-4" />}>
      <p className="text-[11px] text-slate-300 mb-2">
        Imported strategies cannot trade directly. They start backtest-only. Broker access is blocked.
        Live trading is locked.
      </p>
      <p className="text-[10px] text-slate-500 mb-2">{importedMsg || "Loading import status…"}</p>
      <textarea
        value={manifest}
        onChange={(e) => setManifest(e.target.value)}
        className="w-full h-16 text-[9px] font-mono bg-black/40 border border-white/10 rounded p-2 mb-2"
      />
      <button
        type="button"
        disabled={!canImport}
        onClick={doImport}
        className="text-[10px] text-hive-cyan mb-2 disabled:opacity-40"
      >
        Import manifest
      </button>
      {list.length === 0 ? (
        <p className="text-[10px] text-slate-500">No strategies imported yet.</p>
      ) : (
        <ul className="text-[10px] text-slate-400 space-y-1 max-h-[120px] overflow-y-auto">
          {list.map((s) => (
            <li key={String(s.strategy_id)}>
              {String(s.name || s.strategy_id)} — stage {String(s.current_stage)}
            </li>
          ))}
        </ul>
      )}
      {msg && <p className="text-[10px] text-slate-400 mt-2">{msg}</p>}
    </GlassPanel>
  );
}
