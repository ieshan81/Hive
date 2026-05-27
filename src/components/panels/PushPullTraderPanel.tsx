"use client";

import { useCallback, useEffect, useState } from "react";
import { TrendingUp } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";
import { PushPullCandleCard, PaperOrderProofPanel } from "@/components/panels/PushPullCandleCard";

export function PushPullTraderPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [decisions, setDecisions] = useState<Record<string, unknown>[]>([]);
  const [lessons, setLessons] = useState<Record<string, unknown>[]>([]);
  const [signals, setSignals] = useState<Record<string, unknown> | null>(null);
  const [latestTick, setLatestTick] = useState<Record<string, unknown> | null>(null);
  const [orderProof, setOrderProof] = useState<Record<string, unknown> | null>(null);
  const [diagnosis, setDiagnosis] = useState<Record<string, unknown> | null>(null);
  const [signalSymbol, setSignalSymbol] = useState("BTC/USD");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const ps = await apiGet<Record<string, unknown>>("/api/page-state/push-pull");
    if (ps.ok && ps.data) {
      const d = ps.data;
      setStatus({
        operator_messages: [String(d.next_action ?? "")],
        entry_safety: d.entry_safety,
        why_blocked: d.why_blocked,
      });
      setLatestTick((d.latest_tick as Record<string, unknown>) ?? null);
      setOrderProof((d.paper_order_proof as Record<string, unknown>) ?? null);
      setLessons((d.lessons as Record<string, unknown>[]) ?? []);
      setDiagnosis({
        no_trade_reasons: d.no_trade_reasons,
        next_action: d.next_action,
        experiments: d.experiments,
      });
      setDecisions([]);
    }
    setLoading(false);
  }, [signalSymbol]);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
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

      <PushPullCandleCard tick={latestTick} />
      <PaperOrderProofPanel proof={orderProof} />
      {Boolean(diagnosis?.why_no_order) ? (
        <GlassPanel title="Why no order?">
          <p className="text-xs text-slate-300">{String(diagnosis?.why_no_order)}</p>
          {Boolean(diagnosis?.operator_next_action) ? (
            <p className="text-[11px] text-hive-cyan mt-2">{String(diagnosis?.operator_next_action)}</p>
          ) : null}
        </GlassPanel>
      ) : null}

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

      <GlassPanel title="Push-Pull signal">
        <div className="flex gap-2 mb-2">
          <input
            className="rounded bg-black/40 border border-white/10 px-2 py-1 text-xs text-white w-32"
            value={signalSymbol}
            onChange={(e) => setSignalSymbol(e.target.value)}
            placeholder="BTC/USD"
          />
          <button
            type="button"
            className="text-[10px] px-2 py-1 rounded bg-hive-cyan/20 text-hive-cyan"
            onClick={() => void load()}
          >
            Refresh
          </button>
        </div>
        {signals?.push_pull_labels ? (
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            {Object.entries(signals.push_pull_labels as Record<string, unknown>).map(([k, v]) => (
              <div key={k}>
                <span className="text-slate-500">{k.replace(/_/g, " ")}: </span>
                <span className="text-white">{String(v ?? "—")}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500">No signal data yet.</p>
        )}
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
