import { AIFundManagerPanel } from "@/components/panels/AIFundManagerPanel";
import { HiveMindSection } from "@/components/panels/HiveMindSection";
import { getDashboardData } from "@/lib/dashboard";

export default async function AIManagerPage() {
  const data = await getDashboardData();
  return (
    <section className="max-w-4xl">
      <AIFundManagerPanel data={data.aiFundManager} />
      <HiveMindSection />
    </section>
  );
}
