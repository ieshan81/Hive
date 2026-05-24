import { Sidebar } from "@/components/layout/Sidebar";
import { TopStatusBar } from "@/components/layout/TopStatusBar";
import { getDashboardData } from "@/lib/dashboard";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const data = await getDashboardData();
  return (
    <div className="min-h-screen">
      <Sidebar systemStatus={data.systemStatus} />
      <main className="ml-[220px] min-h-screen p-5 lg:p-6">
        <TopStatusBar lastSync={data.lastSync} statusChips={data.statusChips} systemStatus={data.systemStatus} />
        {children}
      </main>
    </div>
  );
}
