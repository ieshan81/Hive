"use client";

import { useEffect, useState } from "react";
import type { EndpointProbe } from "@/lib/apiHealth";
import { probeApiEndpoints } from "@/lib/apiHealth";
import { buildApiUrl } from "@/lib/apiClient";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function SystemLogModal({ open, onClose }: Props) {
  const [probes, setProbes] = useState<EndpointProbe[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    probeApiEndpoints().then((p) => {
      setProbes(p);
      setLoading(false);
    });
  }, [open]);

  if (!open) return null;

  const base = buildApiUrl("/") || "(relative /api via Next rewrite)";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="w-full max-w-2xl max-h-[85vh] bg-slate-900 border border-white/10 rounded-xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex justify-between items-center px-4 py-3 border-b border-white/10">
          <h2 className="text-sm font-semibold text-white">System Log — API endpoint health</h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white text-xs">
            Close
          </button>
        </header>
        <div className="p-4 overflow-auto max-h-[calc(85vh-3rem)] text-xs space-y-3">
          <p className="text-slate-500 font-mono break-all">API base: {base}</p>
          {loading ? (
            <p className="text-slate-500">Probing endpoints…</p>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="text-slate-500 border-b border-white/5">
                  <th className="text-left py-1">Status</th>
                  <th className="text-left">Path</th>
                  <th className="text-left">Keys</th>
                  <th className="text-left">Count</th>
                </tr>
              </thead>
              <tbody>
                {probes.map((p) => (
                  <tr key={p.path} className="border-b border-white/5 text-slate-300">
                    <td className={`py-1.5 pr-2 ${p.ok ? "text-emerald-400" : "text-red-400"}`}>
                      {p.ok ? "OK" : "FAIL"} {p.status}
                    </td>
                    <td className="py-1.5 pr-2 font-mono text-[10px]">{p.path}</td>
                    <td className="py-1.5 pr-2 text-[10px] text-slate-500">{p.rawKeys.join(", ") || "—"}</td>
                    <td className="py-1.5">{p.itemCount ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {probes.some((p) => !p.ok) && (
            <ul className="space-y-1 text-red-300/90">
              {probes
                .filter((p) => !p.ok)
                .map((p) => (
                  <li key={p.path} className="font-mono text-[10px]">
                    {p.url}: {p.error}
                    {p.corsBlocked ? " (possible CORS)" : ""}
                  </li>
                ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
