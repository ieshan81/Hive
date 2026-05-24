import { getDashboardData } from "@/lib/dashboard";
import { StrategyLabPanel } from "@/components/panels/StrategyLabPanel";

export default async function StrategiesPage() {
  const data = await getDashboardData();
  return <StrategyLabPanel strategies={data.strategies} />;
}
