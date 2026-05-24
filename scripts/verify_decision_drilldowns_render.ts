import assert from "node:assert";
import { normalizeApproved, normalizeBlocked } from "../src/lib/apiNormalize";

function run() {
  const blocked = normalizeBlocked({
    status: "ok",
    count: 4,
    decisions: [
      { symbol: "ARB/USD" },
      { symbol: "BTC/USDC" },
      { symbol: "BTC/USDT" },
      { symbol: "DOGE/USDC" },
    ],
  });
  assert.strictEqual(blocked.length, 4, "4 blocked rows from API shape");

  const approved = normalizeApproved({
    status: "ok",
    decisions: [{ symbol: "DOGE/USD", status: "approved" }],
  });
  assert.strictEqual(approved.length, 1);

  const emptyOk = normalizeBlocked({ status: "ok", decisions: [] });
  assert.strictEqual(emptyOk.length, 0, "true empty only when array length 0");

  console.log("verify_decision_drilldowns_render: OK");
}

run();
