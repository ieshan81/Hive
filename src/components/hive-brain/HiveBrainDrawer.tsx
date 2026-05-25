"use client";

import { X } from "lucide-react";
import type { HiveBrainNodeDrawer } from "@/types/hiveBrain";

interface Props {
  node: HiveBrainNodeDrawer | null;
  loading?: boolean;
  onClose: () => void;
}

function EvidenceRow({ label, value }: { label: string; value: unknown }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="flex justify-between gap-2 py-0.5 border-b border-white/5">
      <span className="text-slate-500 shrink-0">{label}</span>
      <span className="text-slate-200 text-right break-all">{String(value)}</span>
    </div>
  );
}

export function HiveBrainDrawer({ node, loading, onClose }: Props) {
  if (!node && !loading) return null;

  const evidence = node?.sections?.evidence ?? {};
  const summary = node?.sections?.summary ?? {};
  const isPosition = node?.type === "position";

  return (
    <aside className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-[#0a0f18]/95 border-l border-cyan-500/20 shadow-2xl overflow-y-auto p-4">
      <div className="flex items-start justify-between gap-2 mb-3">
        <div>
          <p className="text-[10px] text-cyan-400 uppercase tracking-wide">Node detail</p>
          <h3 className="text-sm font-semibold text-slate-100">{node?.title || node?.full_label || "Loading…"}</h3>
          {node?.type && <p className="text-[10px] text-slate-500 mt-0.5">{node.type} · {node.shape}</p>}
        </div>
        <button type="button" onClick={onClose} className="p-1 text-slate-400 hover:text-white" aria-label="Close drawer">
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading && <p className="text-[11px] text-slate-400">Loading node proof…</p>}

      {node && (
        <>
          {node.summary && <p className="text-[11px] text-slate-300 mb-3">{node.summary}</p>}

          {isPosition && (
            <section className="mb-4 p-3 rounded-lg border border-cyan-500/30 bg-cyan-950/20">
              <p className="text-[10px] font-semibold text-cyan-300 mb-2">Broker source proof (required)</p>
              <EvidenceRow label="Source" value={node.source} />
              <EvidenceRow label="Source endpoint" value={node.source_endpoint} />
              <EvidenceRow label="Source table" value={node.source_table} />
              <EvidenceRow label="broker_order_id" value={evidence.broker_order_id} />
              <EvidenceRow label="signal_id" value={evidence.signal_id} />
              <EvidenceRow label="true_hold_minutes" value={evidence.true_hold_minutes} />
              <EvidenceRow label="hold_time_source" value={evidence.hold_time_source} />
              <EvidenceRow label="stale_status" value={evidence.stale_status} />
              <EvidenceRow label="stale" value={evidence.stale} />
              <EvidenceRow label="action" value={evidence.action} />
              <EvidenceRow label="original_filled_at" value={evidence.original_filled_at} />
              <EvidenceRow label="broker_synced_at" value={evidence.broker_synced_at} />
              {evidence.hold_time_warning != null && evidence.hold_time_warning !== "" ? (
                <p className="text-[10px] text-amber-400 mt-2">{String(evidence.hold_time_warning)}</p>
              ) : null}
            </section>
          )}

          {Object.keys(summary).length > 0 && (
            <section className="mb-3">
              <p className="text-[10px] font-semibold text-slate-400 mb-1">Summary</p>
              {Object.entries(summary).map(([k, v]) => (
                <EvidenceRow key={k} label={k.replace(/_/g, " ")} value={v} />
              ))}
            </section>
          )}

          {!isPosition && Object.keys(evidence).length > 0 && (
            <section className="mb-3">
              <p className="text-[10px] font-semibold text-slate-400 mb-1">Evidence</p>
              {Object.entries(evidence).map(([k, v]) => (
                <EvidenceRow key={k} label={k.replace(/_/g, " ")} value={v} />
              ))}
            </section>
          )}

          {node.sections?.linked_items && Object.keys(node.sections.linked_items).length > 0 && (
            <section>
              <p className="text-[10px] font-semibold text-slate-400 mb-1">Linked</p>
              {Object.entries(node.sections.linked_items).map(([k, v]) => (
                <EvidenceRow key={k} label={k} value={Array.isArray(v) ? v.join(", ") : v} />
              ))}
            </section>
          )}
        </>
      )}
    </aside>
  );
}
