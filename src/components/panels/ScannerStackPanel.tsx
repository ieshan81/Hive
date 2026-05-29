"use client";

import { useCallback, useEffect, useState } from "react";
import { Cpu, RefreshCw } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type Scanner = {
  id: string;
  label: string;
  description: string;
};

type Latest = {
  scanners: Record<string, { status: string; elapsed_ms: number; ran_at?: string; error?: string }>;
};

export function ScannerStackPanel() {
  const [list, setList] = useState<Scanner[]>([]);
  const [latest, setLatest] = useState<Latest | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const load = useCallback(async () => {
    const [statusR, latestR] = await Promise.all([
      apiGet<{ scanners: Scanner[] }>("/api/scanners/status"),
      apiGet<Latest>("/api/scanners/latest"),
    ]);
    if (statusR.ok && statusR.data) setList(statusR.data.scanners || []);
    if (latestR.ok && latestR.data) setLatest(latestR.data);
  }, []);

  const runScanners = useCallback(async () => {
    setRunning(true);
    await apiPostOperator("/api/scanners/run-once?symbols=BTC/USD,ETH/USD,SOL/USD,DOGE/USD");
    await load();
    setRunning(false);
  }, [load]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      await load();
      setLoading(false);
    })();
  }, [load, runScanners]);

  const stateOf = (id: string) => latest?.scanners?.[id];

  return (
    <GlassPanel
      title="Scanner Stack"
      icon={<Cpu className="h-4 w-4" style={{ color: "#00dbe9" }} />}
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <p className="text-[11px] text-[#b9cacb]">
          10 scanners feed the ranker (read-only). Risk/Eligibility = cage gates, not a risk score.
        </p>
        <button
          type="button"
          onClick={runScanners}
          disabled={running}
          className="flex items-center gap-1 text-[10px] text-hive-cyan border border-hive-cyan/30 rounded px-2 py-1 shrink-0"
        >
          <RefreshCw className={`h-3 w-3 ${running ? "animate-spin" : ""}`} />
          Run
        </button>
      </div>

      {loading ? (
        <p className="text-[11px] text-[#849495]">Loading scanner status…</p>
      ) : (
        <div className="space-y-1.5">
          {list.map((sc) => {
            const s = stateOf(sc.id);
            const color = !s ? "#849495" : s.status === "ok" ? "#00FF66" : "#EF4444";
            const label = !s ? "NOT RUN" : s.status === "ok" ? "OK" : "ERROR";
            return (
              <div
                key={sc.id}
                className="flex items-center gap-3 rounded-md border border-white/[0.06] bg-white/[0.02] px-2.5 py-2"
              >
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{
                    backgroundColor: color,
                    boxShadow: s?.status === "ok" ? "0 0 5px rgba(0,255,102,0.5)" : undefined,
                  }}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-semibold text-[#e3e2e8] truncate">{sc.label}</p>
                  <p className="text-[10px] text-[#849495] truncate">{sc.description}</p>
                </div>
                <span
                  className="label-caps text-[9px] px-1.5 py-0.5 rounded shrink-0"
                  style={{ backgroundColor: `${color}1a`, color, border: `1px solid ${color}44` }}
                >
                  {label}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </GlassPanel>
  );
}
