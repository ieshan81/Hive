"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { AssetIcon } from "@/components/ui/AssetIcon";
import { apiGet } from "@/lib/apiClient";

type Score = {
  symbol: string;
  pass: boolean;
  reason?: string;
  reasons?: string[];
  push_score: number;
  edge_bps: number;
  quality_score: number;
  universe_rank_score?: number;
  sentiment_alignment?: number;
  regime?: string;
  five_m_confirms?: boolean;
};

type Payload = {
  status: string;
  generated_at_utc?: string;
  scores: Score[];
  passed_count?: number;
  symbols_evaluated?: number;
};

function chipColor(value: number, kind: "push" | "edge" | "quality"): string {
  if (kind === "edge") return value > 25 ? "#00FF66" : value < 0 ? "#EF4444" : "#F59E0B";
  if (value > 70) return "#00FF66";
  if (value > 50) return "#F59E0B";
  return "#849495";
}

function reasonLabel(r?: string): string {
  if (!r || r === "ok") return "Passed";
  return r.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

export function PushPullLiveScoresPanel() {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await apiGet<Payload>("/api/strategy/push-pull/scores");
    if (r.ok && r.data) setData(r.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <GlassPanel
      title="Push-Pull Live Scores"
      icon={<Activity className="h-4 w-4" style={{ color: "#00dbe9" }} />}
    >
      <p className="text-[11px] text-[#b9cacb] mb-3">
        Live scoring uses the research formulas — push_score, edge_after_cost_bps,
        trade_quality_score, regime, 5m confirmation. Sentiment cap ±10%.
      </p>

      {loading ? (
        <p className="text-[11px] text-[#849495]">Loading live scores…</p>
      ) : !data?.scores?.length ? (
        <p className="text-[11px] text-[#849495]">No symbols scored. Alpaca may be unconfigured.</p>
      ) : (
        <div className="space-y-2">
          <div className="text-[10px] text-[#849495] mono-metric mb-1">
            {data.passed_count ?? 0} / {data.symbols_evaluated ?? data.scores.length} passed entry gates
          </div>

          {data.scores.map((s) => (
            <div
              key={s.symbol}
              className="rounded-md border border-white/[0.06] bg-white/[0.02] p-3"
            >
              <div className="flex items-center gap-3 mb-2">
                <AssetIcon symbol={s.symbol} size="sm" />
                <div className="flex-1 min-w-0">
                  <p className="text-[12px] font-semibold text-[#e3e2e8]">{s.symbol}</p>
                  <p className="text-[10px] text-[#849495]">
                    regime: <span style={{ color: "#b9cacb" }}>{s.regime ?? "—"}</span>
                    {s.five_m_confirms !== undefined && (
                      <>
                        {" · 5m confirm: "}
                        <span style={{ color: s.five_m_confirms ? "#00FF66" : "#F59E0B" }}>
                          {s.five_m_confirms ? "yes" : "no"}
                        </span>
                      </>
                    )}
                  </p>
                </div>
                <span
                  className="text-[10px] px-2 py-0.5 rounded-md label-caps"
                  style={{
                    backgroundColor: s.pass ? "rgba(0,255,102,0.1)" : "rgba(245,158,11,0.1)",
                    color: s.pass ? "#00FF66" : "#F59E0B",
                    border: `1px solid ${s.pass ? "rgba(0,255,102,0.25)" : "rgba(245,158,11,0.25)"}`,
                  }}
                >
                  {s.pass ? "PASS" : "BLOCKED"}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-2 text-[10px]">
                <div>
                  <p className="text-[#849495] label-caps mb-0.5">Push</p>
                  <p className="mono-metric font-bold text-[14px]" style={{ color: chipColor(s.push_score, "push") }}>
                    {s.push_score.toFixed(0)}
                  </p>
                </div>
                <div>
                  <p className="text-[#849495] label-caps mb-0.5">Edge</p>
                  <p className="mono-metric font-bold text-[14px]" style={{ color: chipColor(s.edge_bps, "edge") }}>
                    {s.edge_bps > 0 ? "+" : ""}
                    {s.edge_bps.toFixed(0)}bps
                  </p>
                </div>
                <div>
                  <p className="text-[#849495] label-caps mb-0.5">Quality</p>
                  <p className="mono-metric font-bold text-[14px]" style={{ color: chipColor(s.quality_score, "quality") }}>
                    {s.quality_score.toFixed(0)}
                  </p>
                </div>
              </div>

              {!s.pass && (
                <p className="text-[10px] text-[#F59E0B] mt-2">
                  Blocked: {reasonLabel(s.reason)}
                  {s.reasons && s.reasons.length > 1 && ` (+${s.reasons.length - 1} more)`}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </GlassPanel>
  );
}
