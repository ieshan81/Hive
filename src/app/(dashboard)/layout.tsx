import { DashboardShell } from "@/components/layout/DashboardShell";
import { SafetyBanner } from "@/components/layout/SafetyBanner";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopStatusBar } from "@/components/layout/TopStatusBar";
import { getDashboardData } from "@/lib/dashboard";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const data = await getDashboardData();
  return (
    <DashboardShell>
      <div className="relative z-10 min-h-screen">
        <Sidebar systemStatus={data.systemStatus} />
        <main className="ml-[240px] min-h-screen p-5 lg:p-6">
          <TopStatusBar
            lastSync={data.lastSync}
            lastSyncAt={data.lastSyncAt}
            statusChips={data.statusChips}
            systemStatus={data.systemStatus}
          />
          <SafetyBanner />
          {children}
        </main>
      </div>
    </DashboardShell>
  );
}
