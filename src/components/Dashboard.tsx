import { AccountSurvivalPanel } from "@/components/panels/AccountSurvivalPanel";
import { AIFundManagerPanel } from "@/components/panels/AIFundManagerPanel";
import { DynamicMarketRadarPanel } from "@/components/panels/DynamicMarketRadarPanel";
import { HiveMemoryGraphPanel } from "@/components/panels/HiveMemoryGraphPanel";
import { MonteCarloPanel } from "@/components/panels/MonteCarloPanel";
import { RiskCagePanel } from "@/components/panels/RiskCagePanel";
import { StrategyLabPanel } from "@/components/panels/StrategyLabPanel";
import { ExecutionPolicyPanel } from "@/components/panels/ExecutionPolicyPanel";
import { PortfolioGatePanel } from "@/components/panels/PortfolioGatePanel";
import { OrdersPanel } from "@/components/panels/OrdersPanel";
import { PositionsPanel } from "@/components/panels/PositionsPanel";
import { LatestCyclePanel } from "@/components/panels/LatestCyclePanel";
import { MissionControlPanel } from "@/components/panels/MissionControlPanel";
import type { DashboardData } from "@/types/dashboard";

interface DashboardProps {
  data: DashboardData;
}

export function Dashboard({ data }: DashboardProps) {
  return (
    <>
      <MissionControlPanel data={data} />
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-4">
        <AccountSurvivalPanel data={data.accountSurvival} />
        <AIFundManagerPanel data={data.aiFundManager} />
        <HiveMemoryGraphPanel />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-4 items-stretch">
        <LatestCyclePanel data={data.latestCycle ?? { cycleRunId: null, riskBlocked: 0, riskApproved: 0, portfolioSelected: 0, portfolioDeferred: 0, ordersSubmitted: 0, observations: 0 }} />
        <ExecutionPolicyPanel data={data.executionPolicy ?? { paperOrdersEnabled: false, liveOrdersEnabled: false, whyNoOrder: "—" }} />
        <PortfolioGatePanel data={data.portfolioGate ?? { rankedCount: 0, selectedCount: 0, deferredCount: 0, topN: 1, decisions: [], truthMessage: "—" }} />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-4 items-stretch">
        <OrdersPanel data={data.orders ?? { count: 0, items: [] }} />
        <PositionsPanel data={data.positionsPanel ?? { count: 0, items: [] }} />
        <StrategyLabPanel strategies={data.strategies} />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-4 items-stretch">
        <RiskCagePanel rules={data.riskRules} />
        <DynamicMarketRadarPanel
          assets={data.marketAssets}
          refreshedAt={data.marketRadarMeta.refreshedAt}
          opportunitiesScanned={data.marketRadarMeta.opportunitiesScanned}
          statusMessage={data.marketRadarMeta.message}
        />
        <div />
      </div>
      <MonteCarloPanel data={data.monteCarlo} backtestMessage={data.backtest.message} />
    </>
  );
}
