import { GlassPanel } from "@/components/ui/GlassPanel";
import type { DashboardData } from "@/types/dashboard";

export function LatestCyclePanel({
  data,
}: {
  data: NonNullable<DashboardData["latestCycle"]>;
}) {
  if (!data.cycleRunId) {
    return (
      <GlassPanel title="Latest Cycle" className="h-full">
        <p className="text-sm text-zinc-500">No cycle run yet</p>
      </GlassPanel>
    );
  }
  return (
    <GlassPanel title="Latest Cycle" className="h-full">
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <span className="text-zinc-500">Risk blocked</span>
          <p className="text-lg text-red-400">{data.riskBlocked}</p>
        </div>
        <div>
          <span className="text-zinc-500">Risk approved</span>
          <p className="text-lg text-emerald-400">{data.riskApproved}</p>
        </div>
        <div>
          <span className="text-zinc-500">Selected</span>
          <p className="text-lg text-cyan-400">{data.portfolioSelected}</p>
        </div>
        <div>
          <span className="text-zinc-500">Deferred</span>
          <p className="text-lg text-amber-400">{data.portfolioDeferred}</p>
        </div>
        <div>
          <span className="text-zinc-500">Orders submitted</span>
          <p className="text-lg">{data.ordersSubmitted}</p>
        </div>
        <div>
          <span className="text-zinc-500">Observations</span>
          <p className="text-lg">{data.observations}</p>
        </div>
      </div>
      <p className="text-[10px] text-zinc-600 mt-2 truncate">{data.cycleRunId}</p>
    </GlassPanel>
  );
}
