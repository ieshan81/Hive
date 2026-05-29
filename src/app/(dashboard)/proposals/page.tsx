import { CodeProposalsPanel } from "@/components/panels/CodeProposalsPanel";
import { StrategyProposalsPanel } from "@/components/panels/StrategyProposalsPanel";

export default function ProposalsPage() {
  return (
    <section className="max-w-4xl space-y-4">
      <StrategyProposalsPanel />
      <CodeProposalsPanel />
    </section>
  );
}
