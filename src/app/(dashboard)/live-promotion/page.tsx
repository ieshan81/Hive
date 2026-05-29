import { LiveReadinessFlagsPanel } from "@/components/panels/LiveReadinessFlagsPanel";
import { LivePromotionPanel } from "@/components/panels/LivePromotionPanel";

export default function LivePromotionPage() {
  return (
    <section className="max-w-4xl space-y-4">
      <LivePromotionPanel />
      <LiveReadinessFlagsPanel />
    </section>
  );
}
