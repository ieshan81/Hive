import { PushPullLiveScoresPanel } from "@/components/panels/PushPullLiveScoresPanel";
import { PushPullTraderPanel } from "@/components/panels/PushPullTraderPanel";
import { CandleChartPanel } from "@/components/panels/CandleChartPanel";
import { RecentPaperTradesPanel } from "@/components/panels/RecentPaperTradesPanel";

export default function PushPullPage() {
  return (
    <section className="space-y-4">
      <PushPullLiveScoresPanel />
      <CandleChartPanel defaultSymbol="DOGE/USD" />
      <RecentPaperTradesPanel />
      <PushPullTraderPanel />
    </section>
  );
}
