import { StrategyRegistryPanel } from "@/components/panels/StrategyRegistryPanel";
import { StrategyImportPanel } from "@/components/panels/StrategyImportPanel";
import { AlphaFactoryPanel } from "@/components/panels/AlphaFactoryPanel";

export default function StrategiesPage() {
  return (
    <div className="space-y-4">
      <AlphaFactoryPanel compact={false} />
      <StrategyRegistryPanel />
      <StrategyImportPanel />
    </div>
  );
}
