import { UniverseRadarFunnel } from "@/components/panels/UniverseRadarFunnel";
import { UniversePanel } from "@/components/panels/UniversePanel";

export default function UniversePage() {
  return (
    <section className="space-y-4">
      <UniverseRadarFunnel />
      <UniversePanel />
    </section>
  );
}
