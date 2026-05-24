import { getDashboardData } from "@/lib/dashboard";
import { AIFundManagerPanel } from "@/components/panels/AIFundManagerPanel";
import { EmptyState } from "@/components/ui/EmptyState";

export default async function AIManagerPage() {
  const data = await getDashboardData();
  return (
    <section className="max-w-3xl">
      <AIFundManagerPanel data={data.aiFundManager} />
      {data.memoryGraph.nodes.length === 0 && (
        <div className="mt-4">
          <EmptyState message="No AI memories yet — run a cycle after real activity" />
        </div>
      )}
    </section>
  );
}
