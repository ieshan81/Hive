"use client";

import { useEffect, useState } from "react";
import { FileArchive, AlertTriangle } from "lucide-react";
import { apiGet, apiPostOperator, buildApiUrl, DIAGNOSTIC_POLL_MS } from "@/lib/apiClient";

export function DiagnosticBundlePanel() {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [bundleStatus, setBundleStatus] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    void apiGet<Record<string, unknown>>("/api/diagnostics/export/status").then((r) => {
      if (r.ok && r.data) setBundleStatus(r.data);
    });
  }, []);

  useEffect(() => {
    if (!jobId || !busy) return;
    const poll = setInterval(async () => {
      const st = await apiGet<{
        export_in_progress?: boolean;
        last_completed?: { job_id?: string; filename?: string; file_count?: number };
      }>("/api/diagnostics/export/status", { timeoutMs: DIAGNOSTIC_POLL_MS });
      if (!st.ok || !st.data) return;
      if (!st.data.export_in_progress && st.data.last_completed?.job_id === jobId) {
        setBusy(false);
        const lc = st.data.last_completed;
        setMsg(
          `Ready: ${lc?.filename ?? "bundle.zip"} (${lc?.file_count ?? "?"} files). Click download.`
        );
      }
    }, DIAGNOSTIC_POLL_MS);
    return () => clearInterval(poll);
  }, [jobId, busy]);

  async function startExport() {
    setBusy(true);
    setMsg("Starting export…");
    const res = await apiPostOperator<{ job_id?: string }>("/api/diagnostics/export/run", {});
    if (!res.ok || !res.data?.job_id) {
      setMsg(res.error ?? "Could not start export");
      setBusy(false);
      return;
    }
    setJobId(res.data.job_id);
    setMsg("Export running in background — do not refresh the whole page.");
  }

  async function downloadReady() {
    if (!jobId) return;
    const url = buildApiUrl(`/api/diagnostics/export/download/${jobId}`, false);
    try {
      const res = await fetch(url, { method: "GET" });
      if (!res.ok) {
        setMsg(`Download not ready (${res.status})`);
        return;
      }
      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") || "";
      const match = cd.match(/filename="([^"]+)"/);
      const filename = match?.[1] || "caged-hive-diagnostic.zip";
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
      setMsg(e instanceof Error ? e.message : "Download failed");
    }
  }

  const readable = (bundleStatus?.readable_status as Record<string, string>) ?? {};
  const exportJob = bundleStatus?.export_job as Record<string, unknown> | undefined;
  const last = exportJob?.last_completed as Record<string, unknown> | undefined;

  return (
    <section className="max-w-3xl space-y-4">
      <article className="rounded-xl border border-white/10 bg-white/3 p-6">
        <h2 className="text-lg font-semibold text-white mb-2 flex items-center gap-2">
          <FileArchive className="h-5 w-5 text-hive-cyan" /> Reports — Diagnostic proof package
        </h2>
        <dl className="grid grid-cols-2 gap-2 text-sm mb-4">
          {Object.entries(readable).map(([k, v]) => (
            <div key={k}>
              <dt className="text-slate-500 capitalize">{k.replace(/_/g, " ")}</dt>
              <dd className="text-white font-medium">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={startExport}
            className="inline-flex items-center rounded-lg border border-hive-cyan/30 bg-hive-cyan/10 px-4 py-2 text-sm font-medium text-hive-cyan hover:bg-hive-cyan/20 disabled:opacity-50"
          >
            {busy ? "Export running…" : "Start export"}
          </button>
          {jobId && !busy && (
            <button
              type="button"
              onClick={downloadReady}
              className="inline-flex items-center rounded-lg border border-white/20 px-4 py-2 text-sm text-white hover:bg-white/5"
            >
              Download ready bundle
            </button>
          )}
        </div>
        {last?.filename ? (
          <p className="text-[11px] text-slate-500 mt-2">
            Last bundle: {String(last.filename)} · {String(last.file_count ?? "?")} files
          </p>
        ) : null}
        {msg && (
          <p
            className={`mt-3 text-[11px] flex items-start gap-2 ${
              msg.includes("failed") || msg.includes("not ready") ? "text-amber-300" : "text-slate-400"
            }`}
          >
            {(msg.includes("failed") || msg.includes("not ready")) && (
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            )}
            {msg}
          </p>
        )}
        <button
          type="button"
          className="text-[11px] text-slate-500 mt-3 underline"
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? "Hide" : "Show"} technical details
        </button>
        {expanded && bundleStatus?.technical_details != null && (
          <pre className="mt-2 text-[10px] text-slate-600 overflow-auto max-h-40 p-2 rounded bg-black/40">
            {JSON.stringify(bundleStatus.technical_details, null, 2)}
          </pre>
        )}
      </article>
    </section>
  );
}
