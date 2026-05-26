"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";
import { onHiveNukeComplete } from "@/lib/hiveRefresh";
import { PushPullCandleCard } from "@/components/panels/PushPullCandleCard";

type FeedEvent = { at?: string; kind?: string; message?: string };

export function ActivityFeedPanel() {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [latestTick, setLatestTick] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [res, tick] = await Promise.all([
      apiGet<{ events?: FeedEvent[] }>("/api/activity/feed?limit=80"),
      apiGet<Record<string, unknown>>("/api/push-pull/latest-tick"),
    ]);
    if (res.ok) setEvents(res.data?.events ?? []);
    if (tick.ok) setLatestTick(tick.data);
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
      <p className="text-sm text-slate-400">Bot life in plain English — ticks, scans, skips, lessons, resets.</p>

      <PushPullCandleCard tick={latestTick} title="Latest push-pull candle cycle" />

      <GlassPanel title="Recent events">
        {events.length === 0 ? (
          <p className="text-sm text-slate-500">No activity yet. Start paper learning or wait for the first tick.</p>
        ) : (
          <ul className="space-y-2 max-h-[70vh] overflow-y-auto">
            {events.map((e, i) => (
              <li key={`${e.at}-${i}`} className="text-[11px] border-b border-white/5 pb-2">
                <span className="text-slate-500">{e.at}</span>{" "}
                <span className="text-white">{e.message}</span>
                {e.kind && <span className="text-slate-600 ml-1">({e.kind})</span>}
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>
    </section>
  );
}
