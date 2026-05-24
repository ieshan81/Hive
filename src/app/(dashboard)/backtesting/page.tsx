import { getDashboardData } from "@/lib/dashboard";
import { MonteCarloPanel } from "@/components/panels/MonteCarloPanel";
import { ResearchLabPanel } from "@/components/panels/ResearchLabPanel";

export default async function BacktestingPage() {
  const data = await getDashboardData();
  return (
    <section className="space-y-6 max-w-5xl">
      <ResearchLabPanel />
      <MonteCarloPanel data={data.monteCarlo} backtestMessage={data.backtest.message} />
    </section>
  );
}
