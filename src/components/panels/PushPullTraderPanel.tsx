"use client";

import { useCallback, useEffect, useState } from "react";
import { TrendingUp } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";

export function PushPullTraderPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [decisions, setDecisions] = useState<Record<string, unknown>[]>([]);
  const [lessons, setLessons] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [st, dec, les] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/push-pull/status"),
      apiGet<{ decisions?: Record<string, unknown>[] }>("/api/push-pull/decisions?limit=30"),
      apiGet<{ lessons?: Record<string, unknown>[] }>("/api/push-pull/lessons?limit=15"),
    ]);
    if (st.ok) setStatus(st.data);
    if (dec.ok) setDecisions(dec.data?.decisions ?? []);
    if (les.ok) setLessons(les.data?.lessons ?? []);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 45000);
    return () => clearInterval(t);
  }, [load]);

  if (loading) return <EmptyState message="Loading Push-Pull Trader…" />;

  const msgs = (status?.operator_messages as string[]) ?? [];

  return (
    <section className="space-y-4 max-w-5xl">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <TrendingUp className="h-6 w-6 text-hive-cyan" />
        Push-Pull Trader
      </h1>
      <p className="text-sm text-slate-400">Scan → Push → Entry → Pull/Exit → Learn</p>

      <GlassPanel title="Market mode">
        <p className="text-white text-sm">{String(status?.market_mode_label ?? status?.market_mode)}</p>
        <div className="flex flex-wrap gap-2 mt-2">
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            Stocks: {status?.stock_push_pull_active ? "Active" : "Off"}
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            Crypto: {status?.crypto_push_pull_active ? "Active" : "Off"}
          </span>
        </div>
        {msgs.map((m) => (
          <p key={m} className="text-[11px] text-slate-500 mt-1">
            {m}
          </p>
        ))}
      </GlassPanel>

      <GlassPanel title="Recent decisions">
        {decisions.length === 0 ? (
          <p className="text-sm text-slate-500">No push-pull decisions yet.</p>
        ) : (
          <ul className="space-y-2 max-h-[320px] overflow-y-auto">
            {decisions.map((d) => (
              <li key={String(d.id)} className="text-[11px] border-b border-white/5 pb-2">
                <span className="text-white font-medium">{String(d.symbol)}</span> — {String(d.action)}{" "}
                {d.historical ? (
                  <span className="text-slate-600">(historical)</span>
                ) : (
                  <span className="text-cyan-400">(latest)</span>
                )}
                <p className="text-slate-500">{String(d.reason_plain ?? d.reason_text)}</p>
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>

      <GlassPanel title="Latest lessons">
        {lessons.length === 0 ? (
          <p className="text-sm text-slate-500">No lessons saved yet.</p>
        ) : (
          <ul className="space-y-2">
            {lessons.map((l) => (
              <li key={String(l.id)} className="text-[11px] text-slate-400">
                <span className="text-white">{String(l.title)}</span>
                <p>{String(l.lesson_plain ?? l.summary)}</p>
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>
    </section>
  );
}
