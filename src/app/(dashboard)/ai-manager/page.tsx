import { AIFundManagerPanel } from "@/components/panels/AIFundManagerPanel";
import { CleanMindPanel } from "@/components/panels/CleanMindPanel";
import { HiveMindSection } from "@/components/panels/HiveMindSection";
import { getDashboardData } from "@/lib/dashboard";

export default async function AIManagerPage() {
  const data = await getDashboardData();
  return (
    <section className="max-w-4xl space-y-6">
      <AIFundManagerPanel data={data.aiFundManager} />
      <CleanMindPanel />
      <HiveMindSection />
    </section>
  );
}
