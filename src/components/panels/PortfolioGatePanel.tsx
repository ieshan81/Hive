import { GlassPanel } from "@/components/ui/GlassPanel";
import type { DashboardData } from "@/types/dashboard";

export function PortfolioGatePanel({ data }: { data: DashboardData["portfolioGate"] }) {
  return (
    <GlassPanel title="Portfolio Gate" className="h-full">
      <div className="text-sm space-y-2">
        <p className="text-zinc-400">
          Top-{data.topN}: {data.selectedCount} selected, {data.deferredCount} deferred
        </p>
        <ul className="space-y-1 max-h-40 overflow-y-auto">
          {data.decisions.map((d) => (
            <li key={`${d.symbol}-${d.rank}`} className="flex justify-between text-xs">
              <span>
                #{d.rank} {d.symbol}
              </span>
              <span className={d.selected ? "text-emerald-400" : "text-amber-400"}>
                {d.reason ?? d.status}
              </span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-zinc-500 border-t border-white/10 pt-2">{data.truthMessage}</p>
      </div>
    </GlassPanel>
  );
}
