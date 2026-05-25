import { StrategyRegistryPanel } from "@/components/panels/StrategyRegistryPanel";
import { StrategyImportPanel } from "@/components/panels/StrategyImportPanel";

export default function StrategiesPage() {
  return (
    <div className="space-y-4">
      <StrategyRegistryPanel />
      <StrategyImportPanel />
    </div>
  );
}
