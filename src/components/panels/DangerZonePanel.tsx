"use client";

import { useEffect, useState } from "react";
import { Skull, Trash2 } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";
import { dispatchHiveNukeComplete } from "@/lib/hiveRefresh";

interface DangerZonePanelProps {
  embedded?: boolean;
}

export function DangerZonePanel({ embedded = false }: DangerZonePanelProps) {
  const [msg, setMsg] = useState<string | null>(null);
  const [nukeDetail, setNukeDetail] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [nukePreview, setNukePreview] = useState<Record<string, unknown> | null>(null);
  const [readyPreview, setReadyPreview] = useState<Record<string, unknown> | null>(null);

  async function loadPreviews() {
    const [n, r] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/danger-zone/nuke-everything/preview"),
      apiGet<Record<string, unknown>>("/api/danger-zone/ready-for-live-cleanup/preview"),
    ]);
    if (n.ok) setNukePreview(n.data);
    if (r.ok) setReadyPreview(r.data);
  }

  useEffect(() => {
    loadPreviews();
  }, []);

  async function nuke() {
    const phrase = window.prompt('Type exactly: NUKE CAGED HIVE');
    if (phrase !== "NUKE CAGED HIVE") {
      setMsg("Cancelled — confirmation phrase did not match.");
      return;
    }
    setBusy(true);
    setNukeDetail(null);
    const res = await apiPostOperator("/api/danger-zone/nuke-everything", {
      confirmation: "NUKE CAGED HIVE",
    });
    setBusy(false);
    const data = res.data as {
      status?: string;
      reason?: string;
      required?: string;
      message?: string;
      reset_epoch?: Record<string, unknown>;
      post_nuke_counts?: Record<string, number>;
      rows_deleted?: Record<string, unknown>;
      ticker_may_create_post_nuke_memories?: boolean;
    };
    if (data?.status === "refused" && data.reason === "confirmation_phrase_mismatch") {
      setMsg(`Confirmation failed. Type exactly: ${data.required ?? "NUKE CAGED HIVE"}`);
      return;
    }
    if (res.ok && data?.status === "ok") {
      dispatchHiveNukeComplete({
        reset_epoch_id: data.reset_epoch?.reset_epoch_id,
        post_nuke_counts: data.post_nuke_counts,
      });
      setNukeDetail(data as Record<string, unknown>);
    }
    setMsg(res.ok ? String(data?.message ?? "Nuke complete.") : res.error ?? "Failed");
  }

  async function readyCleanup() {
    const phrase = window.prompt('Type exactly: READY CLEANUP');
    if (phrase !== "READY CLEANUP") {
      setMsg("Cancelled — confirmation phrase did not match.");
      return;
    }
    setBusy(true);
    const res = await apiPostOperator("/api/danger-zone/ready-for-live-cleanup", {
      confirmation: "READY CLEANUP",
    });
    setBusy(false);
    const data = res.data as { status?: string; reason?: string; required?: string; message?: string };
    if (data?.status === "refused" && data.reason === "confirmation_phrase_mismatch") {
      setMsg(`Confirmation failed. Type exactly: ${data.required ?? "READY CLEANUP"}`);
      return;
    }
    setMsg(res.ok ? String(data?.message ?? "Cleanup complete.") : res.error ?? "Failed");
  }

  const uxNotes = (nukePreview?.ux_notes as string[]) ?? [
    "This deletes all learned brain/data. It does not wipe Railway volume.",
    "This keeps schema and live safety.",
    "Do not manually wipe Railway volume/database for normal reset.",
  ];

  return (
    <section className={embedded ? "space-y-6" : "max-w-2xl space-y-6"}>
      {!embedded && (
        <>
          <h1 className="text-xl font-bold text-red-300 flex items-center gap-2">
            <Skull className="h-6 w-6" />
            Danger Zone
          </h1>
          <p className="text-sm text-slate-400">
            Destructive actions require operator auth. Neither action enables live trading.
          </p>
        </>
      )}

      <GlassPanel title="NUKE EVERYTHING">
        <ul className="text-[11px] text-amber-200/90 list-disc pl-4 mb-2 space-y-1">
          {uxNotes.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
        <p className="text-[10px] text-slate-500 mb-2">
          Typed confirmation required: <span className="font-mono text-slate-300">NUKE CAGED HIVE</span>
        </p>
        <ul className="text-[10px] text-slate-500 list-disc pl-4 mb-3 max-h-32 overflow-y-auto">
          {((nukePreview?.will_delete as string[]) ?? []).slice(0, 12).map((x) => (
            <li key={x}>{x}</li>
          ))}
          {((nukePreview?.will_delete as string[]) ?? []).length > 12 && (
            <li>…and {((nukePreview?.will_delete as string[]) ?? []).length - 12} more tables</li>
          )}
        </ul>
        <button
          type="button"
          disabled={busy}
          onClick={nuke}
          className="text-xs border border-red-500/50 bg-red-500/10 text-red-300 px-3 py-2 rounded flex items-center gap-1"
        >
          <Trash2 className="h-3.5 w-3.5" />
          NUKE EVERYTHING
        </button>
        {nukeDetail && (
          <div className="mt-3 text-[10px] text-slate-400 border border-white/5 rounded p-2 space-y-1">
            <p className="text-emerald-300/90">Fresh brain — reset complete.</p>
            <p>
              Reset epoch:{" "}
              <span className="font-mono">
                {String((nukeDetail.reset_epoch as Record<string, unknown>)?.reset_epoch_id ?? "—")}
              </span>
            </p>
            <p>
              Ticker may create new post-nuke memories:{" "}
              {nukeDetail.ticker_may_create_post_nuke_memories ? "yes" : "no (learning off or env pause)"}
            </p>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="READY FOR LIVE TRADE CLEANUP">
        <p className="text-[11px] text-slate-400 mb-2">
          Removes paper junk while keeping proven strategies and useful memories. Does NOT enable live
          trading.
        </p>
        <ul className="text-[10px] text-slate-500 list-disc pl-4 mb-3">
          {((readyPreview?.will_archive_or_delete as string[]) ?? []).map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
        <button
          type="button"
          disabled={busy}
          onClick={readyCleanup}
          className="text-xs border border-amber-500/40 text-amber-200 px-3 py-2 rounded"
        >
          READY FOR LIVE TRADE CLEANUP
        </button>
      </GlassPanel>

      {msg && <p className="text-sm text-slate-300">{msg}</p>}
    </section>
  );
}
