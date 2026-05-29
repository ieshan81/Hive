"use client";

import { ShieldAlert } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { TickerSymbol } from "@/components/ui/TickerSymbol";

type Blocker = { code?: string; count?: number; label?: string };
type Candidate = {
  symbol?: string;
  trade_quality_score?: number;
  quality_score?: number;
  no_trade_reason?: string;
};

type WhyNoTradeCardProps = {
  plain?: string | null;
  topBlockers?: Blocker[];
  topCandidate?: Candidate | null;
  shortlisted?: number;
  eligible?: number;
  canPlacePaperOrders?: boolean;
  pushPullStatus?: string | null;
};

function label(value: unknown): string {
  return String(value ?? "-").replace(/_/g, " ");
}

function pctScore(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return n <= 1 ? `${Math.round(n * 100)}` : `${Math.round(n)}`;
}

export function WhyNoTradeCard({
  plain,
  topBlockers = [],
  topCandidate,
  shortlisted = 0,
  eligible = 0,
  canPlacePaperOrders,
  pushPullStatus,
}: WhyNoTradeCardProps) {
  return (
    <GlassPanel title="Why no trade?" icon={<ShieldAlert className="h-4 w-4 text-amber-400" />}>
      <div className="grid grid-cols-3 gap-2 text-[11px]">
        <div className="rounded border border-white/10 bg-black/20 p-2">
          <p className="text-slate-500">Eligible</p>
          <p className="text-white font-semibold">{eligible}</p>
        </div>
        <div className="rounded border border-white/10 bg-black/20 p-2">
          <p className="text-slate-500">Shortlisted</p>
          <p className="text-white font-semibold">{shortlisted}</p>
        </div>
        <div className="rounded border border-white/10 bg-black/20 p-2">
          <p className="text-slate-500">Paper orders</p>
          <p className={canPlacePaperOrders ? "text-emerald-300 font-semibold" : "text-amber-300 font-semibold"}>
            {canPlacePaperOrders ? "Ready" : "Blocked"}
          </p>
        </div>
      </div>

      {plain ? <p className="mt-3 text-xs text-slate-300">{plain}</p> : null}

      {topCandidate?.symbol ? (
        <div className="mt-3 rounded border border-cyan-300/15 bg-cyan-300/[0.04] p-3 text-[11px]">
          <p className="mb-1 text-slate-500">Top candidate from latest persisted scan</p>
          <div className="flex items-center justify-between gap-3">
            <TickerSymbol symbol={String(topCandidate.symbol)} size="sm" labelClassName="text-sm text-white" />
            <span className="text-hive-cyan">Q{pctScore(topCandidate.trade_quality_score ?? topCandidate.quality_score)}</span>
          </div>
          {topCandidate.no_trade_reason ? (
            <p className="mt-1 text-amber-200">Blocker: {label(topCandidate.no_trade_reason)}</p>
          ) : null}
        </div>
      ) : null}

      {topBlockers.length > 0 ? (
        <div className="mt-3">
          <p className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">Top blockers</p>
          <div className="flex flex-wrap gap-1.5">
            {topBlockers.slice(0, 6).map((b) => (
              <span key={String(b.code)} className="rounded border border-amber-300/20 bg-amber-300/10 px-2 py-1 text-[11px] text-amber-200">
                {label(b.label ?? b.code)}: {Number(b.count ?? 0)}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <p className="mt-3 text-[11px] text-slate-500">No blocker breakdown has been persisted yet.</p>
      )}

      {pushPullStatus ? <p className="mt-3 text-[11px] text-slate-500">Push-pull status: {label(pushPullStatus)}</p> : null}
    </GlassPanel>
  );
}
