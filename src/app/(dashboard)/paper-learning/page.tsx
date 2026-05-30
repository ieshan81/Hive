import { PaperAutopilotPanel } from "@/components/panels/PaperAutopilotPanel";
import { AutonomousPaperLearningPanel } from "@/components/panels/AutonomousPaperLearningPanel";
import { CapitalAllocatorPanel } from "@/components/panels/CapitalAllocatorPanel";
import { PositionMonitorPanel } from "@/components/panels/PositionMonitorPanel";
import { PaperJournalPanel } from "@/components/panels/PaperJournalPanel";

export default function PaperLearningPage() {
  return (
    <section className="max-w-4xl space-y-4">
      <PaperAutopilotPanel />
      <AutonomousPaperLearningPanel />
      <CapitalAllocatorPanel />
      <PositionMonitorPanel />
      <PaperJournalPanel />
    </section>
  );
}
