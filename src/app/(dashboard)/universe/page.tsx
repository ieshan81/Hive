import { UniverseRadarFunnel } from "@/components/panels/UniverseRadarFunnel";
import { UniversePanel } from "@/components/panels/UniversePanel";
import { CandleChartPanel } from "@/components/panels/CandleChartPanel";
import { DynamicWeightsPanel } from "@/components/panels/DynamicWeightsPanel";

export default function UniversePage() {
  return (
    <section className="space-y-4">
      <UniverseRadarFunnel />
      <div className="grid gap-4 lg:grid-cols-2">
        <CandleChartPanel />
        <DynamicWeightsPanel />
      </div>
      <UniversePanel />
    </section>
  );
}
