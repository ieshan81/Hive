"use client";

import { Radar } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { AssetIcon } from "@/components/ui/AssetIcon";
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

function classStyles(assetClass?: string) {
  if (assetClass === "crypto") return "bg-violet-500/15 text-violet-300 border-violet-500/25";
  return "bg-sky-500/15 text-sky-300 border-sky-500/25";
}

function metricLabel(label: string, value: string | number | null) {
  const display =
    value === null || value === undefined ? "No data" : typeof value === "number" ? `${Math.round(value)}` : value;
  const empty = display === "No data";
  return (
    <div>
      <p className="text-[8px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={cn("text-[11px] font-medium truncate", empty ? "text-slate-600" : "text-slate-300")}>{display}</p>
    </div>
  );
}

function RadarRow({ asset }: { asset: MarketAsset }) {
  return (
    <li className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2.5 hover:border-white/10 transition-colors">
      <div className="flex items-start gap-2.5">
        <AssetIcon symbol={asset.symbol} assetClass={asset.assetClass} size="md" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <p className="text-xs font-semibold text-white truncate">{asset.symbol}</p>
            <span className={cn("rounded px-1.5 py-0.5 text-[8px] font-bold uppercase border", classStyles(asset.assetClass))}>
              {asset.assetClass ?? "—"}
            </span>
            <span className={cn("rounded px-1.5 py-0.5 text-[8px] font-bold uppercase border", eligibilityStyles(asset.eligibility))}>
              {asset.eligibility}
            </span>
          </div>
          {asset.name && asset.name !== asset.symbol && (
            <p className="text-[10px] text-slate-500 truncate mt-0.5">{asset.name}</p>
          )}
          <div className="mt-2 grid grid-cols-4 gap-2">
            {metricLabel("Liq", asset.liquidity)}
            {metricLabel("Sent", asset.sentiment)}
            {metricLabel("Vol", asset.volatility)}
            <div>
              <p className="text-[8px] uppercase tracking-wider text-slate-500">Spread</p>
              <p className="text-[11px] font-medium text-slate-300 truncate">{asset.spread}</p>
            </div>
          </div>
        </div>
      </div>
    </li>
  );
}

export function DynamicMarketRadarPanel({
  assets,
  refreshedAt,
  opportunitiesScanned,
  statusMessage,
}: DynamicMarketRadarPanelProps) {
  return (
    <GlassPanel title="Dynamic Market Radar" icon={<Radar className="h-4 w-4" />} className="h-full flex flex-col">
      {assets.length === 0 ? (
        <EmptyState message={statusMessage ?? "No market data — run POST /api/cycle/run"} />
      ) : (
        <ul className="space-y-2 max-h-[420px] overflow-y-auto overflow-x-hidden pr-0.5 scrollbar-thin flex-1">
          {assets.map((asset) => (
            <RadarRow key={`${asset.symbol}-${asset.assetClass}`} asset={asset} />
          ))}
        </ul>
      )}
      <footer className="flex flex-wrap items-center justify-between gap-2 mt-3 pt-2 border-t border-white/5 text-[10px] text-slate-500 shrink-0">
        <span>Refreshed {refreshedAt ? `${formatShortTime(refreshedAt)} local` : "—"}</span>
        <span>{opportunitiesScanned} scanned</span>
      </footer>
    </GlassPanel>
  );
}
