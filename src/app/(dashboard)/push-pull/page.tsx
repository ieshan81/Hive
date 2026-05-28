import { PushPullLiveScoresPanel } from "@/components/panels/PushPullLiveScoresPanel";
import { PushPullTraderPanel } from "@/components/panels/PushPullTraderPanel";
import { CandleChartPanel } from "@/components/panels/CandleChartPanel";
import { DynamicWeightsPanel } from "@/components/panels/DynamicWeightsPanel";
import { RecentPaperTradesPanel } from "@/components/panels/RecentPaperTradesPanel";

export default function PushPullPage() {
  return (
    <section className="space-y-4">
      <PushPullLiveScoresPanel />
      <div className="grid gap-4 lg:grid-cols-2">
        <CandleChartPanel defaultSymbol="DOGE/USD" />
        <DynamicWeightsPanel />
      </div>
      <RecentPaperTradesPanel />
      <PushPullTraderPanel />
    </section>
  );
}
