"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface LessonDetail {
  node_id: string;
  title: string;
  summary: string;
  detailed_lesson: string;
  what_happened?: string;
  bot_learned?: string;
  severity: string;
  confidence: number;
  source: string;
  action_status: string;
  proposed_action?: string | null;
  proposed_prevention?: string | null;
  symbol?: string | null;
  strategy_name?: string | null;
  cycle_run_id?: string | null;
  broker_order_id?: string | null;
  occurrence_count?: number;
  evidence_human?: { label: string; value: string }[];
}

interface Props {
  detail: LessonDetail | null;
  onClose: () => void;
  onUpdated?: () => void;
}

export function MemoryLessonDrawer({ detail, onClose, onUpdated }: Props) {
  const [busy, setBusy] = useState(false);
  if (!detail) return null;

  const lessonId = detail.node_id.startsWith("lesson-")
    ? parseInt(detail.node_id.replace("lesson-", ""), 10)
    : null;

  async function act(path: string) {
    if (!lessonId) return;
    setBusy(true);
    try {
      await fetch(`${API_BASE}/api/memory/lesson/${lessonId}/${path}`, { method: "POST" });
      onUpdated?.();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={onClose}>
      <div
        className="w-full max-w-md h-full bg-slate-900 border-l border-white/10 p-5 overflow-y-auto shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-4">
          <h2 className="text-lg font-semibold text-hive-cyan">Lesson Learned</h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white text-sm">
            Close
          </button>
        </div>
        <p className="text-xs text-slate-500 mb-1">{detail.severity} · {detail.source}</p>
        <h3 className="text-base font-medium text-white mb-2">{detail.title}</h3>
        <section className="space-y-3 text-sm">
          <div>
            <p className="text-slate-500 text-xs uppercase tracking-wide">Summary</p>
            <p className="text-slate-300">{detail.summary}</p>
          </div>
          <div>
            <p className="text-slate-500 text-xs uppercase tracking-wide">What happened</p>
            <p className="text-slate-300">{detail.what_happened || detail.summary}</p>
          </div>
          <div>
            <p className="text-slate-500 text-xs uppercase tracking-wide">Bot learned</p>
            <p className="text-slate-300">{detail.bot_learned || detail.detailed_lesson}</p>
          </div>
          {detail.proposed_prevention && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide">Proposed prevention</p>
              <p className="text-amber-200/90">{detail.proposed_prevention}</p>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2 text-xs">
            {detail.symbol && (
              <div>
                <span className="text-slate-500">Symbol</span>
                <p>{detail.symbol}</p>
              </div>
            )}
            {detail.strategy_name && (
              <div>
                <span className="text-slate-500">Strategy</span>
                <p>{detail.strategy_name}</p>
              </div>
            )}
            {detail.cycle_run_id && (
              <div className="col-span-2">
                <span className="text-slate-500">Cycle</span>
                <p className="truncate font-mono text-[10px]">{detail.cycle_run_id}</p>
              </div>
            )}
            {detail.broker_order_id && (
              <div className="col-span-2">
                <span className="text-slate-500">Broker order</span>
                <p className="truncate font-mono text-[10px]">{detail.broker_order_id}</p>
              </div>
            )}
          </div>
          <div>
            <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Evidence</p>
            <ul className="space-y-1">
              {(detail.evidence_human || []).map((e) => (
                <li key={e.label} className="flex justify-between text-xs border-b border-white/5 py-1">
                  <span className="text-slate-500">{e.label}</span>
                  <span className="text-slate-300 text-right max-w-[60%]">{e.value}</span>
                </li>
              ))}
            </ul>
          </div>
          <p className="text-xs text-slate-500">
            Confidence {(detail.confidence * 100).toFixed(0)}% · Status {detail.action_status}
            {detail.occurrence_count != null && detail.occurrence_count > 1
              ? ` · Seen ${detail.occurrence_count}×`
              : ""}
          </p>
        </section>
        {lessonId && (
          <div className="flex gap-2 mt-6 pt-4 border-t border-white/10">
            <button
              type="button"
              disabled={busy}
              onClick={() => act("approve")}
              className="flex-1 py-2 text-xs rounded bg-emerald-600/80 hover:bg-emerald-600 text-white"
            >
              Approve lesson
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => act("reject")}
              className="flex-1 py-2 text-xs rounded bg-red-900/60 hover:bg-red-800 text-white"
            >
              Reject
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
