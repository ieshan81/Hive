import { GlassPanel } from "@/components/ui/GlassPanel";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import type { DashboardData } from "@/types/dashboard";

export function PositionsPanel({
  data,
}: {
  data: NonNullable<DashboardData["positionsPanel"]>;
}) {
  return (
    <GlassPanel title="Broker Positions" className="h-full">
      {data.count === 0 ? (
        <p className="text-sm text-zinc-500">No open broker positions</p>
      ) : (
        <ul className="space-y-2 text-xs">
          {data.items.map((p) => (
            <li key={p.symbol} className="flex justify-between items-center gap-2">
              <TickerSymbol symbol={p.symbol} size="sm" labelClassName="text-xs text-zinc-200" />
              <span>
                {p.qty} @ {p.avgEntryPrice?.toFixed(4)}
                {p.unrealizedPl != null && (
                  <span className={p.unrealizedPl >= 0 ? " text-emerald-400" : " text-red-400"}>
                    {" "}
                    ({p.unrealizedPl >= 0 ? "+" : ""}
                    {p.unrealizedPl.toFixed(2)})
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}
