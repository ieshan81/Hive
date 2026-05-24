import { getDashboardData } from "@/lib/dashboard";
import { AccountSurvivalPanel } from "@/components/panels/AccountSurvivalPanel";
import { EmptyState } from "@/components/ui/EmptyState";

export default async function PerformancePage() {
  const data = await getDashboardData();
  return (
    <section className="max-w-2xl space-y-4">
      <AccountSurvivalPanel data={data.accountSurvival} />
      <EmptyState message="Trade history appears here after closed paper trades — no fake performance" />
    </section>
  );
}
