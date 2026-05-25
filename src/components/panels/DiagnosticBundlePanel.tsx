"use client";

import { useState } from "react";
import { FileArchive } from "lucide-react";
import { getDiagnosticBundleUrl } from "@/lib/dashboard";

const REQUIRED_FILES = [
  "doge_broker_availability_audit.json",
  "broker_position_availability_audit.json",
  "ghost_position_candidates.json",
  "fast_training_status.json",
  "hive_brain_node_details_sample.json",
  "live_lock_tripwire_status.json",
  "positions.json",
  "orders.json",
];

export function DiagnosticBundlePanel() {
  const [expanded, setExpanded] = useState(false);

  return (
    <section className="max-w-xl space-y-4">
      <article className="rounded-xl border border-white/10 bg-white/3 p-6">
        <h2 className="text-lg font-semibold text-white mb-2 flex items-center gap-2">
          <FileArchive className="h-5 w-5 text-hive-cyan" /> Diagnostic bundle
        </h2>
        <p className="text-sm text-slate-400 mb-4">
          Download a zip of API snapshots for audit. Secrets are never included. After download, verify
          required files inside the zip.
        </p>
        <a
          href={getDiagnosticBundleUrl()}
          className="inline-flex items-center rounded-lg border border-hive-cyan/30 bg-hive-cyan/10 px-4 py-2 text-sm font-medium text-hive-cyan hover:bg-hive-cyan/20"
        >
          Export diagnostic bundle
        </a>
        <ul className="mt-4 text-[11px] text-slate-400 space-y-1">
          {REQUIRED_FILES.map((f) => (
            <li key={f}>✓ {f}</li>
          ))}
        </ul>
        <p className="text-[10px] text-amber-400/80 mt-3">
          Missing files in the zip should be treated as a failed audit until fixed.
        </p>
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
