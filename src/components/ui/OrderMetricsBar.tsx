import type { OrderSummaryCounts } from "@/lib/orderDisplay";

export function OrderMetricsBar({ summary, compact }: { summary?: OrderSummaryCounts; compact?: boolean }) {
  const s = summary ?? {};
  const items = [
    { label: "Attempted", value: s.orders_attempted ?? 0, color: "text-slate-300" },
    { label: "Sent to broker", value: s.orders_sent_to_broker ?? 0, color: "text-cyan-400" },
    { label: "Filled", value: s.orders_filled ?? 0, color: "text-emerald-400" },
    { label: "Rejected", value: s.orders_rejected ?? 0, color: "text-red-400" },
    { label: "Preflight blocked", value: s.orders_blocked_preflight ?? 0, color: "text-amber-400" },
  ];
  return (
    <div className={compact ? "space-y-1" : "space-y-2"}>
      <div className={`grid grid-cols-5 gap-1 ${compact ? "text-[10px]" : "text-xs"}`}>
        {items.map((it) => (
          <div key={it.label} className="rounded border border-white/5 bg-white/[0.02] px-1.5 py-1 text-center">
            <p className={`font-semibold ${it.color}`}>{it.value}</p>
            <p className="text-slate-500 leading-tight">{it.label}</p>
          </div>
        ))}
      </div>
      {s.last_order_user_message ? (
        <p className={`text-slate-500 ${compact ? "text-[10px]" : "text-xs"}`}>{s.last_order_user_message}</p>
      ) : null}
    </div>
  );
}
