/** Lightweight sanity check for confidence panel card keys. */
import { readFileSync } from "fs";
import { join } from "path";

const panel = readFileSync(
  join(process.cwd(), "src/components/panels/ConfidenceLevelPanel.tsx"),
  "utf8"
);
const required = ["Overall", "Strategy", "Market Regime", "Broker Compatibility"];
for (const label of required) {
  if (!panel.includes(label)) {
    console.error("MISSING:", label);
    process.exit(1);
  }
}
console.log("PASS: confidence panel labels present");
