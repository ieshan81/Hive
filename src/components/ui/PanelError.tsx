import type { PanelLoadMeta } from "@/types/api";

interface Props {
  title: string;
  meta: PanelLoadMeta;
  expectedShape?: string;
  receivedKeys?: string[];
}

export function PanelError({ title, meta, expectedShape, receivedKeys }: Props) {
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-xs space-y-1.5">
      <p className="font-semibold text-red-400">{title}</p>
      {meta.endpoint && (
        <p className="text-slate-400 font-mono break-all">
          GET {meta.endpoint}
          {meta.httpStatus != null ? ` → HTTP ${meta.httpStatus}` : ""}
        </p>
      )}
      {meta.error && <p className="text-red-300/90">{meta.error}</p>}
      {expectedShape && <p className="text-slate-500">Expected: {expectedShape}</p>}
      {receivedKeys && receivedKeys.length > 0 && (
        <p className="text-slate-500">Received keys: {receivedKeys.join(", ")}</p>
      )}
      {meta.source === "dashboard_snapshot" && (
        <p className="text-amber-400/90">Showing latest dashboard snapshot; live endpoint failed.</p>
      )}
    </div>
  );
}
