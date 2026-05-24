"use client";

import { Radar } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { RingGauge } from "@/components/ui/RingGauge";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatShortTime } from "@/lib/datetime";
import { cn } from "@/lib/utils";
import type { MarketAsset } from "@/types/dashboard";

interface DynamicMarketRadarPanelProps {
  assets: MarketAsset[];
  refreshedAt: string | null;
  opportunitiesScanned: number;
  statusMessage?: string | null;
}

function eligibilityStyles(status: string) {
  if (status === "ELIGIBLE") return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
  if (status === "CAUTION") return "bg-amber-500/15 text-amber-400 border-amber-500/30";
  if (status === "BLOCKED") return "bg-red-500/15 text-red-400 border-red-500/30";
  return "bg-slate-500/15 text-slate-400 border-slate-500/30";
}

function AssetIcon({ symbol }: { symbol: string }) {
  return (
    <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-white/5 text-[9px] font-bold text-slate-300 border border-white/8">
      {symbol.slice(0, 2)}
    </span>
  );
}

function ScoreCell({ value }: { value: number | null }) {
  if (value === null) return <span className="text-[10px] text-slate-500">—</span>;
  return <RingGauge value={value} />;
}

export function DynamicMarketRadarPanel({
  assets,
  refreshedAt,
  opportunitiesScanned,
  statusMessage,
}: DynamicMarketRadarPanelProps) {
  return (
    <GlassPanel
      title="Dynamic Market Radar"
      icon={<Radar className="h-4 w-4" />}
      className="h-full"
    >
      {assets.length === 0 ? (
        <EmptyState message={statusMessage ?? "No market data — run POST /api/cycle/run"} />
      ) : (
        <div className="w-full overflow-x-auto scrollbar-thin">
          <table className="w-full min-w-[680px] text-left">
            <thead>
              <tr className="border-b border-white/5">
                {["Asset", "Class", "Liquidity", "Sentiment", "Volatility", "Spread", "Eligibility"].map((col) => (
                  <th key={col} className="pb-2 pr-3 text-[9px] font-semibold uppercase tracking-wider text-slate-500 whitespace-nowrap">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={`${asset.symbol}-${asset.assetClass}`} className="border-b border-white/3 last:border-0">
                  <td className="py-2.5 pr-3 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <AssetIcon symbol={asset.symbol} />
                      <div>
                        <p className="text-xs font-semibold text-white">{asset.symbol}</p>
                        <p className="text-[9px] text-slate-500">{asset.name}</p>
                      </div>
                    </div>
                  </td>
                  <td className="py-2.5 pr-3 text-[10px] uppercase text-slate-400">{asset.assetClass ?? "—"}</td>
                  <td className="py-2.5 pr-3"><ScoreCell value={asset.liquidity} /></td>
                  <td className="py-2.5 pr-3"><ScoreCell value={asset.sentiment} /></td>
                  <td className="py-2.5 pr-3"><ScoreCell value={asset.volatility} /></td>
                  <td className="py-2.5 pr-3 text-xs text-slate-400 whitespace-nowrap">{asset.spread}</td>
                  <td className="py-2.5">
                    <span className={cn("inline-block rounded px-2 py-0.5 text-[8px] font-bold tracking-wider border", eligibilityStyles(asset.eligibility))}>
                      {asset.eligibility}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <footer className="flex items-center justify-between mt-3 pt-2 border-t border-white/5 text-[10px] text-slate-500">
        <span>Data refreshed {refreshedAt ? `${formatShortTime(refreshedAt)} local` : "—"}</span>
        <span>{opportunitiesScanned} opportunities scanned</span>
      </footer>
    </GlassPanel>
  );
}
