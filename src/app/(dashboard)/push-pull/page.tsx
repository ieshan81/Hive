import { PushPullLiveScoresPanel } from "@/components/panels/PushPullLiveScoresPanel";
import { PushPullTraderPanel } from "@/components/panels/PushPullTraderPanel";

export default function PushPullPage() {
  return (
    <section className="space-y-4">
      <PushPullLiveScoresPanel />
      <PushPullTraderPanel />
    </section>
  );
}
