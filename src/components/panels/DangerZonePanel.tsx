"use client";

import { useEffect, useState } from "react";
import { Skull, Trash2 } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

export function DangerZonePanel() {
  const [msg, setMsg] = useState<string | null>(null);
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
    const res = await apiPostOperator("/api/danger-zone/nuke-everything", {
      confirmation: "NUKE CAGED HIVE",
    });
    setBusy(false);
    setMsg(res.ok ? String((res.data as { message?: string })?.message ?? "Nuke complete.") : res.error ?? "Failed");
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
    setMsg(
      res.ok
        ? String((res.data as { message?: string })?.message ?? "Cleanup complete.")
        : res.error ?? "Failed"
    );
  }

  return (
    <section className="max-w-2xl space-y-6">
      <h1 className="text-xl font-bold text-red-300 flex items-center gap-2">
        <Skull className="h-6 w-6" />
        Danger Zone
      </h1>
      <p className="text-sm text-slate-400">
        Destructive actions require operator auth. Neither action enables live trading.
      </p>

      <GlassPanel title="NUKE EVERYTHING">
        <p className="text-[11px] text-amber-300 mb-2">
          Deletes memories, lessons, paper artifacts, logs, and diagnostics. Does not pause learning or
          scheduler — only Railway env vars can pause execution.
        </p>
        <ul className="text-[10px] text-slate-500 list-disc pl-4 mb-3">
          {((nukePreview?.will_delete as string[]) ?? []).map((x) => (
            <li key={x}>{x}</li>
          ))}
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
