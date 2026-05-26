import { AutonomousPaperLearningPanel } from "@/components/panels/AutonomousPaperLearningPanel";
import { CapitalAllocatorPanel } from "@/components/panels/CapitalAllocatorPanel";

export default function PaperLearningPage() {
  return (
    <section className="max-w-4xl space-y-4">
      <AutonomousPaperLearningPanel />
      <CapitalAllocatorPanel />
    </section>
  );
}
