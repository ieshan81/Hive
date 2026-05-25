import { GlassPanel } from "@/components/ui/GlassPanel";
import { OrderMetricsBar } from "@/components/ui/OrderMetricsBar";
import { ExecutionOrdersTable } from "@/components/ui/ExecutionOrdersTable";
import type { DashboardData } from "@/types/dashboard";

export function OrdersPanel({
  data,
  orderSummary,
}: {
  data: NonNullable<DashboardData["orders"]>;
  orderSummary?: DashboardData["orderSummary"];
}) {
  const items = (data.items ?? []) as unknown as Record<string, unknown>[];

  return (
    <GlassPanel title="Paper Orders" className="h-full">
      <OrderMetricsBar summary={orderSummary} compact />
      <div className="mt-3">
        {items.length === 0 ? (
          <p className="text-sm text-zinc-500">No orders in the latest cycle view.</p>
        ) : (
          <ExecutionOrdersTable rows={items} mode="order" emptyMessage="No orders" />
        )}
      </div>
    </GlassPanel>
  );
}
