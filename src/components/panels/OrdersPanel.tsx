import { GlassPanel } from "@/components/ui/GlassPanel";
import type { DashboardData } from "@/types/dashboard";

export function OrdersPanel({ data }: { data: NonNullable<DashboardData["orders"]> }) {
  return (
    <GlassPanel title="Paper Orders (latest cycle)" className="h-full">
      {data.count === 0 ? (
        <p className="text-sm text-zinc-500">No orders this cycle</p>
      ) : (
        <ul className="space-y-2 text-xs">
          {data.items.map((o) => (
            <li key={o.brokerOrderId ?? o.clientOrderId ?? o.symbol} className="border-b border-white/5 pb-2">
              <div className="flex justify-between">
                <span className="text-cyan-400">
                  {o.side.toUpperCase()} {o.symbol}
                </span>
                <span>{o.status}</span>
              </div>
              <div className="text-zinc-500">
                qty {o.qty} · {o.orderType}
                {o.filledAvgPrice != null ? ` · fill ${o.filledAvgPrice}` : ""}
              </div>
              {o.brokerOrderId && <div className="text-zinc-600 truncate">id {o.brokerOrderId}</div>}
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}
