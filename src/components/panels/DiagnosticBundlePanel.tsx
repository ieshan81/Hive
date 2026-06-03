"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Download, FileArchive } from "lucide-react";
import { apiGet, apiPostOperator, buildApiUrl, DIAGNOSTIC_POLL_MS } from "@/lib/apiClient";

type DiagnosticJob = {
  job_id?: string;
  status?: string;
  progress_pct?: number;
  current_step?: string | null;
  filename?: string;
  file_count?: number;
  completed_at?: string;
  error?: string;
};

type DiagnosticStatus = {
  export_in_progress?: boolean;
  current_job?: DiagnosticJob | null;
  last_completed?: DiagnosticJob | null;
};

function time(value?: string): string {
  return value ? value.replace("T", " ").replace("Z", "").slice(0, 19) : "-";
}

export function DiagnosticBundlePanel() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [bundleStatus, setBundleStatus] = useState<DiagnosticStatus | null>(null);

  const load = useCallback(async () => {
    const r = await apiGet<DiagnosticStatus>("/api/diagnostics/export/status", { timeoutMs: 4000 });
    if (r.ok && r.data) {
      setBundleStatus(r.data);
      setBusy(Boolean(r.data.export_in_progress));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!busy) return;
    const poll = setInterval(load, DIAGNOSTIC_POLL_MS);
    return () => clearInterval(poll);
  }, [busy, load]);

  const last = bundleStatus?.last_completed ?? null;
  const lastIsForensic = (last?.file_count ?? 0) > 80;

  const latestDownloadUrl = useMemo(
    () => buildApiUrl("/api/diagnostic-bundle/download?mode=latest"),
    []
  );

  async function startBackgroundExport() {
    setBusy(true);
    setMsg("Background export started (latest bundle).");
    const res = await apiPostOperator<{ job_id?: string }>(
      "/api/diagnostics/export/run",
      { mode: "latest" },
      { timeoutMs: 10000 }
    );
    if (!res.ok) setMsg(res.error ?? "Could not start export.");
    await load();
  }

  return (
    <section className="mx-auto max-w-2xl space-y-4">
      <article className="rounded-xl border border-white/10 bg-white/[0.03] p-6">
        <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold text-white">
          <FileArchive className="h-5 w-5 text-hive-cyan" />
          Diagnostic bundle
        </h2>
        <p className="mb-4 text-sm text-slate-400">
          Use the <strong className="font-normal text-slate-200">latest</strong> bundle (~30 files, README_FIRST.json) for
          analysis. Forensic full history is explicit only: <span className="font-mono text-xs">?mode=forensic</span>.
        </p>

        <a
          href={latestDownloadUrl}
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-hive-cyan/40 bg-hive-cyan/10 px-4 py-3 text-sm font-medium text-hive-cyan hover:bg-hive-cyan/20"
        >
          <Download className="h-4 w-4" />
          Download latest bundle now
        </a>

        {lastIsForensic ? (
          <p className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-[11px] text-amber-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            Last background job was a heavy forensic export ({last?.file_count} files). Prefer the button above, or run a
            new export after deploy.
          </p>
        ) : null}

        <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-3 text-[11px] text-slate-400">
          <p>
            Background job: {bundleStatus?.export_in_progress ? "running" : "idle"}
            {last ? ` · last ${last.file_count ?? 0} files @ ${time(last.completed_at)}` : ""}
          </p>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={startBackgroundExport}
            className="rounded-lg border border-white/20 px-3 py-2 text-xs text-white hover:bg-white/5 disabled:opacity-50"
          >
            {busy ? "Export running…" : "Queue background export"}
          </button>
          <button type="button" onClick={load} className="rounded-lg border border-white/20 px-3 py-2 text-xs text-slate-400 hover:bg-white/5">
            Refresh status
          </button>
        </div>

        {msg ? <p className="mt-2 text-[11px] text-slate-500">{msg}</p> : null}
      </article>
    </section>
  );
}
