import assert from "node:assert";
import {
  normalizeOrders,
  normalizePositions,
  normalizePositionStates,
  normalizeTrades,
} from "../src/lib/apiNormalize";

function run() {
  const positions = normalizePositions({
    status: "ok",
    positions: [
      {
        symbol: "DOGEUSD",
        qty: 292.633555314,
        avg_entry_price: 0.102282,
        current_price: 0.10215,
        unrealized_pl: -0.0386,
      },
    ],
  });
  assert.strictEqual(positions[0].symbol, "DOGEUSD");

  const states = normalizePositionStates({
    states: [{ symbol: "DOGEUSD", fee_pct: 0.25, fee_adjusted_qty: 292.633555314 }],
  });
  assert.strictEqual(states[0].fee_pct, 0.25);

  const orders = normalizeOrders({
    orders: [{ symbol: "DOGE/USD", status: "filled", broker_order_id: "17b2d08a" }],
  });
  assert.strictEqual(orders[0].status, "filled");

  const trades = normalizeTrades({
    trades: [{ symbol: "DOGE/USD", side: "buy", status: "open" }],
  });
  assert.ok(trades.length === 1);

  console.log("verify_positions_tab_render: OK");
}

run();
