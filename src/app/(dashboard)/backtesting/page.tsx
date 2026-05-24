import { getDashboardData } from "@/lib/dashboard";
import { MonteCarloPanel } from "@/components/panels/MonteCarloPanel";
import { EmptyState } from "@/components/ui/EmptyState";

export default async function BacktestingPage() {
  const data = await getDashboardData();
  return (
    <section className="space-y-4">
      <MonteCarloPanel data={data.monteCarlo} backtestMessage={data.backtest.message} />
      {data.backtest.status === "not_run" && (
        <EmptyState message="Backtest not run yet — POST /api/backtest/run on the backend" />
      )}
    </section>
  );
}
