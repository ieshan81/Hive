import { AIManagerLearningPanel } from "@/components/panels/AIManagerLearningPanel";
import { HiveMindSection } from "@/components/panels/HiveMindSection";
import { SentimentSourcesPanel } from "@/components/panels/SentimentSourcesPanel";
import { ScannerStackPanel } from "@/components/panels/ScannerStackPanel";

export default function AIManagerPage() {
  return (
    <section className="max-w-4xl space-y-4">
      <SentimentSourcesPanel />
      <ScannerStackPanel />
      <AIManagerLearningPanel />
      <HiveMindSection />
    </section>
  );
}
