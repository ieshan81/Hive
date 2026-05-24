"use client";

import { useState } from "react";

import { apiPost } from "@/lib/apiClient";

export interface LessonDetail {
  node_id: string;
  lesson_id?: number;
  drawer_title?: string;
  category?: string;
  memory_type?: string;
  title: string;
  summary: string;
  detailed_lesson: string;
  what_happened?: string;
  why_it_matters?: string;
  bot_learned?: string | null;
  trading_impact?: string | null;
  system_impact?: string | null;
  severity: string;
  confidence: number;
  source: string;
  action_status: string;
  status?: string;
  visible_to_ai?: boolean;
  visible_in_graph?: boolean;
  can_influence_ranking?: boolean;
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

function ActionBtn({
  children,
  onClick,
  disabled,
  className = "",
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`py-2 px-2 text-[10px] rounded min-w-[72px] ${className}`}
    >
      {children}
    </button>
  );
}

export function MemoryLessonDrawer({ detail, onClose, onUpdated }: Props) {
  const [busy, setBusy] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  if (!detail) return null;

  const lessonId =
    detail.lesson_id ??
    (detail.node_id.startsWith("lesson-") ? parseInt(detail.node_id.replace("lesson-", ""), 10) : null);

  const title = detail.drawer_title || "Lesson Learned";
  async function post(path: string, body?: object) {
    if (!lessonId) return;
    setBusy(true);
    try {
      await apiPost(`/api/memory/lesson/${lessonId}/${path}`, body);
      onUpdated?.();
      if (path !== "visibility") onClose();
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
          <div>
            <h2 className="text-lg font-semibold text-hive-cyan">{title}</h2>
            <p className="text-[10px] text-slate-500 mt-0.5">
              {detail.category} · {detail.memory_type}
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white text-sm">
            Close
          </button>
        </div>
        <p className="text-xs text-slate-500 mb-1">
          {detail.severity} · {detail.source} · {detail.status}
        </p>
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
          {detail.bot_learned && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide">Bot learned</p>
              <p className="text-slate-300">{detail.bot_learned}</p>
            </div>
          )}
          {detail.trading_impact && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide">Trading impact</p>
              <p className="text-cyan-200/80 text-xs">{detail.trading_impact}</p>
            </div>
          )}
          {detail.system_impact && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide">System impact</p>
              <p className="text-orange-200/80 text-xs">{detail.system_impact}</p>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <span className="text-slate-500">Visible to AI</span>
              <p>{detail.visible_to_ai ? "yes" : "no"}</p>
            </div>
            <div>
              <span className="text-slate-500">In graph</span>
              <p>{detail.visible_in_graph ? "yes" : "no"}</p>
            </div>
            <div>
              <span className="text-slate-500">Ranking influence</span>
              <p>{detail.can_influence_ranking ? "yes" : "no"}</p>
            </div>
          </div>
          <button
            type="button"
            className="text-[10px] text-hive-cyan"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? "Hide" : "Show"} evidence JSON
          </button>
          <p className="text-xs text-slate-500">
            Confidence {(detail.confidence * 100).toFixed(0)}% · {detail.action_status}
          </p>
        </section>

        {lessonId && (
          <div className="mt-6 pt-4 border-t border-white/10 space-y-3">
            <p className="text-[10px] uppercase tracking-wide text-slate-500">Memory actions</p>
            <div className="flex flex-wrap gap-2">
              <ActionBtn
                disabled={busy}
                onClick={() => post("archive", { reason: "operator archived", hide_from_ai: true, hide_from_graph: true })}
                className="bg-slate-700 text-white"
              >
                Archive memory
              </ActionBtn>
              <ActionBtn disabled={busy} onClick={() => post("restore")} className="border border-white/10 text-slate-300">
                Restore memory
              </ActionBtn>
              <ActionBtn
                disabled={busy}
                onClick={() => post("delete", { reason: "soft delete by operator" })}
                className="bg-red-900/60 text-white"
              >
                Delete memory
              </ActionBtn>
              <ActionBtn
                disabled={busy}
                onClick={() => post("visibility", { visible_in_graph: false })}
                className="border border-white/10 text-slate-400"
              >
                Hide from graph
              </ActionBtn>
              <ActionBtn
                disabled={busy}
                onClick={() => post("visibility", { visible_to_ai: false, can_influence_ranking: false })}
                className="border border-white/10 text-slate-400"
              >
                Hide from AI
              </ActionBtn>
              <ActionBtn disabled={busy} onClick={() => post("resolve")} className="border border-emerald-500/30 text-emerald-400">
                Mark resolved
              </ActionBtn>
              <ActionBtn
                disabled={busy}
                onClick={() => post("category", { category: "system_issue" })}
                className="bg-orange-900/40 text-orange-200"
              >
                Mark system issue
              </ActionBtn>
              <ActionBtn
                disabled={busy}
                onClick={() => post("category", { category: "trading_memory" })}
                className="bg-cyan-900/40 text-cyan-200"
              >
                Mark trading memory
              </ActionBtn>
              <ActionBtn disabled={busy} onClick={() => post("approve")} className="bg-emerald-600/80 text-white">
                Approve useful
              </ActionBtn>
              <ActionBtn disabled={busy} onClick={() => post("reject")} className="bg-red-900/40 text-red-200">
                Reject useless
              </ActionBtn>
            </div>
            <p className="text-[9px] text-slate-600">Delete is soft-delete; audit trail remains. Hard delete is admin-only later.</p>
          </div>
        )}
      </div>
    </div>
  );
}
