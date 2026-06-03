"use client";

import { useEffect, useState } from "react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

type ShadowStatus = {
  status?: string;
  enabled?: boolean;
  shadow_league_count?: number;
  closest_to_paper_promotion?: {
    symbol?: string;
    level_name?: string;
    missing_evidence?: string[];
  };
  missing_evidence?: string[];
};

export function ShadowLeagueMiniPanel() {
  const [data, setData] = useState<ShadowStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<ShadowStatus>("/api/shadow-league/status", { timeoutMs: 12000 }).then((res) => {
      if (!cancelled && res.ok) setData(res.data ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!data?.enabled && data?.status !== "ok") return null;

  const closest = data.closest_to_paper_promotion;
  const missing = closest?.missing_evidence?.length
    ? closest.missing_evidence
    : data.missing_evidence ?? [];

  return (
    <GlassPanel title="Shadow Trading League" className="border-violet-500/20">
      <div className="grid gap-2 text-sm text-slate-300">
        <p>
          <span className="text-slate-500">League records:</span>{" "}
          <span className="font-mono text-white">{data.shadow_league_count ?? 0}</span>
          <span className="text-xs text-slate-500 ml-2">(no broker orders)</span>
        </p>
        {closest?.symbol ? (
          <p>
            <span className="text-slate-500">Closest to paper promotion:</span>{" "}
            <span className="text-hive-cyan">{closest.symbol}</span>
            {closest.level_name ? (
              <span className="text-xs text-slate-500 ml-1">({closest.level_name})</span>
            ) : null}
          </p>
        ) : (
          <p className="text-slate-500 text-xs">No shadow setups recorded yet this run.</p>
        )}
        {missing.length > 0 ? (
          <p className="text-xs text-amber-200/90">
            Missing evidence: {missing.slice(0, 4).join(", ")}
            {missing.length > 4 ? "…" : ""}
          </p>
        ) : null}
      </div>
    </GlassPanel>
  );
}
