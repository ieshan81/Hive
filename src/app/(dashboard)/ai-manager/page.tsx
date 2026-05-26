import { AIManagerLearningPanel } from "@/components/panels/AIManagerLearningPanel";
import { HiveMindSection } from "@/components/panels/HiveMindSection";

export default function AIManagerPage() {
  return (
    <section className="max-w-4xl space-y-6">
      <AIManagerLearningPanel />
      <HiveMindSection />
    </section>
  );
}
