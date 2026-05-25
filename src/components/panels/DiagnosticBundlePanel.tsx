"use client";

import { useState } from "react";
import { FileArchive, AlertTriangle } from "lucide-react";
import { apiGet, buildApiUrl } from "@/lib/apiClient";

const REQUIRED_FILES = [
  "doge_broker_availability_audit.json",
  "broker_position_availability_audit.json",
  "ghost_position_candidates.json",
  "fast_training_status.json",
  "hive_brain_node_details_sample.json",
  "live_lock_tripwire_status.json",
  "positions.json",
  "orders.json",
  "diagnostic_export_errors.json",
];

export function DiagnosticBundlePanel() {
  const [expanded, setExpanded] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function downloadBundle() {
    setDownloading(true);
    setMsg(null);
    const url = buildApiUrl("/api/diagnostic-bundle/download", false);
    try {
      const res = await fetch(url, { method: "GET" });
      if (!res.ok) {
        const text = await res.text();
        setMsg(
          `Download failed (${res.status}). ${text.slice(0, 200) || "Try again in a moment."}`
        );
        setDownloading(false);
        return;
      }
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = "hive-diagnostic-bundle.zip";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objectUrl);
      const meta = await apiGet<Record<string, unknown>>("/api/diagnostic-bundle");
      const errs = meta.data?.["diagnostic_export_errors.json"];
      if (Array.isArray(errs) && errs.length > 0) {
        setMsg(
          `Bundle downloaded with ${errs.length} section warning(s). Open diagnostic_export_errors.json inside the zip.`
        );
      } else {
        setMsg("Bundle downloaded successfully.");
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Download failed — network or server error.");
    }
    setDownloading(false);
  }

  return (
    <section className="max-w-xl space-y-4">
      <article className="rounded-xl border border-white/10 bg-white/3 p-6">
        <h2 className="text-lg font-semibold text-white mb-2 flex items-center gap-2">
          <FileArchive className="h-5 w-5 text-hive-cyan" /> Diagnostic bundle
        </h2>
        <p className="text-sm text-slate-400 mb-4">
          Download a zip of API snapshots for audit. Secrets are never included. Partial exports include
          diagnostic_export_errors.json when a section fails.
        </p>
        <button
          type="button"
          disabled={downloading}
          onClick={downloadBundle}
          className="inline-flex items-center rounded-lg border border-hive-cyan/30 bg-hive-cyan/10 px-4 py-2 text-sm font-medium text-hive-cyan hover:bg-hive-cyan/20 disabled:opacity-50"
        >
          {downloading ? "Preparing…" : "Export diagnostic bundle"}
        </button>
        {msg && (
          <p
            className={`mt-3 text-[11px] flex items-start gap-2 ${
              msg.includes("warning") || msg.includes("failed")
                ? "text-amber-300"
                : "text-slate-400"
            }`}
          >
            {(msg.includes("failed") || msg.includes("warning")) && (
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            )}
            {msg}
          </p>
        )}
        <ul className="mt-4 text-[11px] text-slate-400 space-y-1">
          {REQUIRED_FILES.map((f) => (
            <li key={f}>✓ {f}</li>
          ))}
        </ul>
        <button
          type="button"
          className="text-[10px] text-hive-cyan mt-2"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Hide" : "View"} JSON format note
        </button>
        {expanded && (
          <p className="text-[9px] text-slate-600 mt-2 font-mono">
            Open JSON files in a text editor after unzip — not shown inline here to avoid leaking raw
            debug dumps on screen.
          </p>
        )}
      </article>
    </section>
  );
}
