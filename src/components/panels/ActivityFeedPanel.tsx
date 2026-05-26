"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, ChevronDown, ChevronUp } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";
import { onHiveNukeComplete } from "@/lib/hiveRefresh";

type FeedEvent = { at?: string; kind?: string; message?: string };

type TickCard = {
  tick_started?: string;
  symbols_scanned?: number;
  candidates_ranked?: number;
  top_candidate?: { symbol?: string; score?: number };
  strategy_used?: string;
  strategy_version?: string;
  scoring_model?: string;
  score?: number;
  why?: string;
  allocator_result?: string;
  validator_result?: string;
  sentiment_status?: string;
  gemini_advisor_status?: string;
  broker_result?: string;
  exit_monitor_result?: string;
  technical?: Record<string, unknown>;
};

function Row({ label, value }: { label: string; value: string | number | undefined | null }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="flex justify-between gap-4 text-sm border-b border-white/5 py-1.5">
      <span className="text-slate-500 shrink-0">{label}</span>
      <span className="text-white text-right">{String(value)}</span>
    </div>
  );
}

export function ActivityFeedPanel() {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [tickCard, setTickCard] = useState<TickCard | null>(null);
  const [showTechnical, setShowTechnical] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [res, cardRes] = await Promise.all([
      apiGet<{ events?: FeedEvent[] }>("/api/activity/feed?limit=80"),
      apiGet<TickCard>("/api/activity/latest-tick-card"),
    ]);
    if (res.ok) setEvents(res.data?.events ?? []);
    if (cardRes.ok) setTickCard(cardRes.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => onHiveNukeComplete(() => void load()), [load]);

  if (loading) return <EmptyState message="Loading activity feed…" />;

  return (
    <section className="space-y-4 max-w-5xl">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <Activity className="h-6 w-6 text-hive-cyan" />
        Activity
      </h1>
      <p className="text-sm text-slate-400">Latest paper tick narrative — scan, score, allocator, broker, exits.</p>

      <GlassPanel title="Latest tick">
        {!tickCard?.tick_started && !tickCard?.why ? (
          <p className="text-sm text-slate-500">No tick completed yet. Run a paper learning cycle from Control Center.</p>
        ) : (
          <div className="space-y-1">
            <Row label="Tick started" value={tickCard?.tick_started} />
            <Row label="Symbols scanned" value={tickCard?.symbols_scanned} />
            <Row label="Candidates ranked" value={tickCard?.candidates_ranked} />
            <Row
              label="Top candidate"
              value={
                tickCard?.top_candidate?.symbol
                  ? `${tickCard.top_candidate.symbol} (${tickCard.top_candidate.score?.toFixed?.(2) ?? tickCard.top_candidate.score})`
                  : undefined
              }
            />
            <Row label="Strategy" value={tickCard?.strategy_used} />
            <Row label="Version" value={tickCard?.strategy_version} />
            <Row label="Score" value={tickCard?.score?.toFixed?.(2) ?? tickCard?.score} />
            <Row label="Decision" value={tickCard?.why} />
            <Row label="Allocator" value={tickCard?.allocator_result} />
            <Row label="Validator" value={tickCard?.validator_result} />
            <Row label="Sentiment" value={tickCard?.sentiment_status} />
            <Row label="Gemini advisor" value={tickCard?.gemini_advisor_status} />
            <Row label="Broker" value={tickCard?.broker_result} />
            <Row label="Exit monitor" value={tickCard?.exit_monitor_result} />
            <button
              type="button"
              onClick={() => setShowTechnical((v) => !v)}
              className="mt-3 flex items-center gap-1 text-[11px] text-hive-cyan"
            >
              {showTechnical ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              Show technical details
            </button>
            {showTechnical && tickCard?.technical && (
              <pre className="mt-2 text-[10px] text-slate-500 overflow-x-auto p-2 rounded bg-black/30">
                {JSON.stringify(tickCard.technical, null, 2)}
              </pre>
            )}
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Recent events">
        {events.length === 0 ? (
          <p className="text-sm text-slate-500">No activity yet. Start paper learning or wait for the first tick.</p>
        ) : (
          <ul className="space-y-2 max-h-[50vh] overflow-y-auto">
            {events.slice(0, 40).map((e, i) => (
              <li key={`${e.at}-${i}`} className="text-[11px] border-b border-white/5 pb-2">
                <span className="text-slate-500">{e.at}</span>{" "}
                <span className="text-white">{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>
    </section>
  );
}
