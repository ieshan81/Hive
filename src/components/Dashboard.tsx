import { AccountSurvivalPanel } from "@/components/panels/AccountSurvivalPanel";
import { AIFundManagerPanel } from "@/components/panels/AIFundManagerPanel";
import { DynamicMarketRadarPanel } from "@/components/panels/DynamicMarketRadarPanel";
import { HiveMemoryGraphPanel } from "@/components/panels/HiveMemoryGraphPanel";
import { MonteCarloPanel } from "@/components/panels/MonteCarloPanel";
import { RiskCagePanel } from "@/components/panels/RiskCagePanel";
import { StrategyLabPanel } from "@/components/panels/StrategyLabPanel";
import type { DashboardData } from "@/types/dashboard";

interface DashboardProps {
  data: DashboardData;
}

export function Dashboard({ data }: DashboardProps) {
  return (
    <>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-4">
        <AccountSurvivalPanel data={data.accountSurvival} />
        <AIFundManagerPanel data={data.aiFundManager} />
        <HiveMemoryGraphPanel memoryGraph={data.memoryGraph} />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-4 items-stretch">
        <StrategyLabPanel strategies={data.strategies} />
        <RiskCagePanel rules={data.riskRules} />
        <DynamicMarketRadarPanel
          assets={data.marketAssets}
          refreshedAt={data.marketRadarMeta.refreshedAt}
          opportunitiesScanned={data.marketRadarMeta.opportunitiesScanned}
          statusMessage={data.marketRadarMeta.message}
        />
      </div>
      <MonteCarloPanel data={data.monteCarlo} backtestMessage={data.backtest.message} />
    </>
  );
}
