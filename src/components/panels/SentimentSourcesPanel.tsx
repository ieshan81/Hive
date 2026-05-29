"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, AlertTriangle } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

type SourceState = {
  active: boolean;
  wired: boolean;
  reason?: string;
  model?: string;
  primary_source?: string;
  fallback_sources?: string[];
  supported_subreddits?: string[];
  endpoint?: string;
};

type SourcesPayload = {
  status: string;
  sources: {
    finbert?: SourceState;
    reddit_social?: SourceState;
    news_feed?: SourceState;
    symbol_candidate_score?: SourceState;
    gemini_advisor?: SourceState;
  };
};

type PumpDumpPayload = {
  active_count: number;
  alerts: { symbol: string; cooldown_until: string; minutes_remaining?: number }[];
};

const SOURCE_ORDER: { key: keyof SourcesPayload["sources"]; label: string }[] = [
  { key: "finbert", label: "FinBERT (local)" },
  { key: "news_feed", label: "News (Alpaca Benzinga)" },
  { key: "gemini_advisor", label: "Gemini Advisor" },
];

export function SentimentSourcesPanel() {
  const [src, setSrc] = useState<SourcesPayload | null>(null);
  const [pump, setPump] = useState<PumpDumpPayload | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [s, p] = await Promise.all([
      apiGet<SourcesPayload>("/api/sentiment/sources"),
      apiGet<PumpDumpPayload>("/api/sentiment/pump-dump-alerts"),
    ]);
    if (s.ok && s.data) setSrc(s.data);
    if (p.ok && p.data) setPump(p.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <GlassPanel
      title="Sentiment Intelligence"
      icon={<Brain className="h-4 w-4" style={{ color: "#8a2be2" }} />}
    >
      <p className="text-[11px] text-[#b9cacb] mb-3">
        Advisory only — sentiment shifts ranking by ≤ ±10%. Execution cage decides.
      </p>

      {loading ? (
        <p className="text-[11px] text-[#849495]">Loading sentiment sources…</p>
      ) : (
        <>
          <div className="space-y-2 mb-4">
            {SOURCE_ORDER.map(({ key, label }) => {
              const s = src?.sources?.[key];
              const active = !!s?.active;
              const wired = !!s?.wired;
              return (
                <div
                  key={key}
                  className="flex items-start gap-3 rounded-md border border-white/[0.06] bg-white/[0.02] p-2.5"
                >
                  <span
                    className="mt-1 h-2 w-2 rounded-full shrink-0"
                    style={{
                      backgroundColor: active ? "#00FF66" : wired ? "#F59E0B" : "#849495",
                      boxShadow: active ? "0 0 6px rgba(0, 255, 102, 0.6)" : undefined,
                    }}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-[12px] font-semibold text-[#e3e2e8]">{label}</p>
                      <span
                        className="label-caps text-[9px] px-1.5 py-0.5 rounded"
                        style={{
                          backgroundColor: active
                            ? "rgba(0, 255, 102, 0.1)"
                            : wired
                            ? "rgba(245, 158, 11, 0.1)"
                            : "rgba(132, 148, 149, 0.1)",
                          color: active ? "#00FF66" : wired ? "#F59E0B" : "#849495",
                        }}
                      >
                        {active ? "Active" : wired ? "Inactive" : "Not Wired"}
                      </span>
                    </div>
                    {s?.reason && (
                      <p className="text-[10px] text-[#849495] mt-1">{s.reason}</p>
                    )}
                    {s?.model && (
                      <p className="text-[10px] text-[#849495] mono-metric mt-0.5">
                        model: {s.model}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {pump && pump.active_count > 0 && (
            <div className="rounded-md border p-2.5 mb-2"
                 style={{
                   borderColor: "rgba(239, 68, 68, 0.3)",
                   backgroundColor: "rgba(239, 68, 68, 0.06)",
                 }}>
              <div className="flex items-center gap-1.5 mb-1">
                <AlertTriangle className="h-3.5 w-3.5" style={{ color: "#EF4444" }} />
                <span className="label-caps" style={{ color: "#EF4444" }}>
                  Pump-Dump Alert · {pump.active_count} active
                </span>
              </div>
              <ul className="space-y-1">
                {pump.alerts.slice(0, 5).map((a) => (
                  <li key={a.symbol} className="text-[10px] text-[#e3e2e8]">
                    <span className="font-semibold">{a.symbol}</span>
                    {a.minutes_remaining !== undefined && (
                      <span className="text-[#849495] mono-metric ml-2">
                        cooldown: {a.minutes_remaining}m
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-[10px] text-[#849495]">
            Cap on sentiment influence: ±10% on trade_quality_score. Never alone permits entry.
          </p>
        </>
      )}
    </GlassPanel>
  );
}
