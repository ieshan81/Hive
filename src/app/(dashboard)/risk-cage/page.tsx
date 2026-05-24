import { getDashboardData } from "@/lib/dashboard";
import { RiskCagePanel } from "@/components/panels/RiskCagePanel";

export default async function RiskCagePage() {
  const data = await getDashboardData();
  return <RiskCagePanel rules={data.riskRules} />;
}
