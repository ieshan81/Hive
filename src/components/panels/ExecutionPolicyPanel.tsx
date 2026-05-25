import { GlassPanel } from "@/components/ui/GlassPanel";
import { orderStatusLabel, orderTypeLabel, rejectReasonPlain, formatDecimal } from "@/lib/orderDisplay";
import type { DashboardData } from "@/types/dashboard";

type ExecutionPolicyData = NonNullable<DashboardData["executionPolicy"]>;

export function ExecutionPolicyPanel({ data }: { data: ExecutionPolicyData }) {
  const enabled = data.paperOrdersEnabled;
  return (
    <GlassPanel title="Execution Policy" className="h-full">
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-zinc-400">Paper orders</span>
          <span className={enabled ? "text-emerald-400" : "text-amber-400"}>
            {enabled ? "ENABLED" : "DISABLED"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-400">Live trading</span>
          <span className="text-emerald-400">LOCKED</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-400">Broker mode</span>
          <span>{data.brokerMode ?? "unknown"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-400">Order type</span>
          <span>
            {(data as { orderTypeLabel?: string }).orderTypeLabel ??
              orderTypeLabel(data.orderTypeDefault ?? "marketable_limit_ioc")}
          </span>
        </div>
        {data.selectedSymbol && (
          <div className="flex justify-between">
            <span className="text-zinc-400">Selected</span>
            <span className="text-cyan-400">{data.selectedSymbol}</span>
          </div>
        )}
        <p className="text-xs text-zinc-500 pt-2 border-t border-white/10">{data.whyNoOrder}</p>
        {data.latestLog && (
          <p className="text-xs text-zinc-400">
            Latest: {data.latestLog.symbol} —{" "}
            {String(
              (data.latestLog as Record<string, unknown>).statusLabel ??
                (data.latestLog as Record<string, unknown>).status_label ??
                orderStatusLabel(data.latestLog.status)
            )}
            {data.latestLog.rejectReason || (data.latestLog as Record<string, unknown>).reject_reason_plain
              ? ` — ${rejectReasonPlain(
                  String(
                    (data.latestLog as Record<string, unknown>).reject_reason_plain ??
                      data.latestLog.rejectReason
                  ),
                  String(data.latestLog.status)
                )}`
              : ""}
            {data.latestLog.limitPrice != null
              ? ` · limit ${formatDecimal((data.latestLog as Record<string, unknown>).limit_price_display ?? data.latestLog.limitPrice)}`
              : ""}
          </p>
        )}
        {(data.paper_execution_blockers as string[] | undefined)?.length ? (
          <ul className="text-xs text-amber-400/90 list-disc pl-4">
            {(data.paper_execution_blockers as string[]).map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </GlassPanel>
  );
}
