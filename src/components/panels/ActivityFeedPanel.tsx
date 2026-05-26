"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";
import { onHiveNukeComplete } from "@/lib/hiveRefresh";

type FeedEvent = { at?: string; kind?: string; message?: string };

export function ActivityFeedPanel() {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await apiGet<{ events?: FeedEvent[] }>("/api/activity/feed?limit=80");
    if (res.ok) setEvents(res.data?.events ?? []);
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
