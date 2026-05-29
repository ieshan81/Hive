"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, FileArchive } from "lucide-react";
import { apiGet, apiPostOperator, buildApiUrl, DIAGNOSTIC_POLL_MS } from "@/lib/apiClient";

type DiagnosticJob = {
  job_id?: string;
  status?: string;
  progress_pct?: number;
  filename?: string;
  file_count?: number;
  completed_at?: string;
  started_at?: string;
  failed_sections?: string[];
  error?: string;
  download_available?: boolean;
};

type DiagnosticStatus = {
  status?: string;
  export_in_progress?: boolean;
  current_job?: DiagnosticJob | null;
  last_completed?: DiagnosticJob | null;
  jobs?: DiagnosticJob[];
};

function time(value?: string): string {
  return value ? value.replace("T", " ").replace("Z", "").slice(0, 19) : "-";
}

function label(value: unknown): string {
  return String(value ?? "-").replace(/_/g, " ");
}

export function DiagnosticBundlePanel() {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [bundleStatus, setBundleStatus] = useState<DiagnosticStatus | null>(null);

  const load = useCallback(async () => {
    const r = await apiGet<DiagnosticStatus>("/api/diagnostics/export/status", { timeoutMs: 4000 });
    if (r.ok && r.data) {
      setBundleStatus(r.data);
      setBusy(Boolean(r.data.export_in_progress));
    } else {
      setMsg(r.error || "Diagnostic status unavailable.");
      setBusy(false);
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
  const current = bundleStatus?.current_job ?? null;
  const failed = useMemo(
    () => (bundleStatus?.jobs ?? []).find((j) => j.status === "failed") ?? null,
    [bundleStatus?.jobs]
  );

  async function startExport() {
    setBusy(true);
    setMsg("Export running in background.");
    const res = await apiPostOperator<{ job_id?: string }>("/api/diagnostics/export/run", {}, { timeoutMs: 10000 });
    if (!res.ok || !res.data?.job_id) {
      setMsg(res.error ?? "Could not start export.");
      setBusy(false);
      return;
    }
    await load();
  }

  async function downloadJob(job?: DiagnosticJob | null) {
    if (!job?.job_id) {
      setMsg("No completed bundle to download.");
      return;
    }
    const url = buildApiUrl(`/api/diagnostics/export/download/${job.job_id}`, false);
    try {
      const res = await fetch(url, { method: "GET" });
      if (!res.ok || !res.headers.get("content-type")?.includes("zip")) {
        const text = await res.text();
        setMsg(text.slice(0, 220) || `Download unavailable (${res.status})`);
        return;
      }
      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") || "";
      const match = cd.match(/filename="([^"]+)"/);
      const filename = match?.[1] || job.filename || "caged-hive-diagnostic.zip";
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objectUrl);
      setMsg(`Downloaded ${filename}`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Download failed.");
    }
  }

  return (
    <section className="max-w-3xl space-y-4">
      <article className="rounded-xl border border-white/10 bg-white/3 p-6">
        <h2 className="mb-2 flex items-center gap-2 text-lg font-semibold text-white">
          <FileArchive className="h-5 w-5 text-hive-cyan" /> Reports
        </h2>
        <p className="mb-4 text-sm text-slate-400">
          Diagnostic exports run as operator jobs. Status is persisted in the database, so refreshing this page keeps the latest job state.
        </p>

        <div className="grid gap-2 text-sm md:grid-cols-3">
          <div className="rounded border border-white/10 bg-black/20 p-3">
            <p className="text-slate-500">Current</p>
            <p className="font-medium text-white">{current ? label(current.status) : "Idle"}</p>
            {current ? <p className="text-[11px] text-slate-500">{current.progress_pct ?? 0}%</p> : null}
          </div>
          <div className="rounded border border-white/10 bg-black/20 p-3">
            <p className="text-slate-500">Last completed</p>
            <p className="font-medium text-white">{last?.filename ?? "-"}</p>
            <p className="text-[11px] text-slate-500">{last?.file_count ?? 0} files · {time(last?.completed_at)}</p>
          </div>
          <div className="rounded border border-white/10 bg-black/20 p-3">
            <p className="text-slate-500">Latest failure</p>
            <p className={failed ? "font-medium text-amber-200" : "font-medium text-white"}>{failed ? label(failed.error ?? failed.status) : "None"}</p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={startExport}
            className="inline-flex items-center rounded-lg border border-hive-cyan/30 bg-hive-cyan/10 px-4 py-2 text-sm font-medium text-hive-cyan hover:bg-hive-cyan/20 disabled:opacity-50"
          >
            {busy ? "Export running..." : "Start export"}
          </button>
          <button
            type="button"
            disabled={!last}
            onClick={() => downloadJob(last)}
            className="inline-flex items-center rounded-lg border border-white/20 px-4 py-2 text-sm text-white hover:bg-white/5 disabled:opacity-50"
          >
            Download last completed bundle
          </button>
          <button
            type="button"
            onClick={load}
            className="inline-flex items-center rounded-lg border border-white/20 px-4 py-2 text-sm text-white hover:bg-white/5"
          >
            Refresh status
          </button>
        </div>

        {failed?.error ? (
          <p className="mt-3 flex items-start gap-2 text-[11px] text-amber-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            Latest failed job: {failed.error}
          </p>
        ) : null}
        {msg ? <p className="mt-3 text-[11px] text-slate-400">{msg}</p> : null}

        <button type="button" className="mt-3 text-[11px] text-slate-500 underline" onClick={() => setExpanded((e) => !e)}>
          {expanded ? "Hide" : "Show"} technical details
        </button>
        {expanded ? (
          <pre className="mt-2 max-h-56 overflow-auto rounded bg-black/40 p-2 text-[10px] text-slate-500">
            {JSON.stringify(bundleStatus, null, 2)}
          </pre>
        ) : null}
      </article>
    </section>
  );
}
