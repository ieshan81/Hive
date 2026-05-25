/** Lightweight sanity check for paper learning panel controls. */
import { readFileSync } from "fs";
import { join } from "path";

const panel = readFileSync(
  join(process.cwd(), "src/components/panels/AutonomousPaperLearningPanel.tsx"),
  "utf8"
);
const required = [
  "autonomous-paper-learning/enable",
  "run-one-cycle",
  "scheduler/enable",
  "Account / pair eligibility",
];
for (const s of required) {
  if (!panel.includes(s)) {
    console.error("MISSING:", s);
    process.exit(1);
  }
}
console.log("PASS: paper learning panel paths present");
