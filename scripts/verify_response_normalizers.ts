import assert from "node:assert";
import {
  normalizeArrayResponse,
  normalizeBlocked,
  normalizeMemoryGraph,
  normalizeOrders,
  normalizePositions,
  normalizeTrades,
} from "../src/lib/apiNormalize";

function run() {
  assert.deepStrictEqual(normalizePositions([{ symbol: "X" }]).length, 1);
  assert.deepStrictEqual(normalizePositions({ positions: [{ symbol: "A" }] }).length, 1);
  assert.deepStrictEqual(normalizePositions({ status: "ok", data: [{ symbol: "B" }] }).length, 1);

  assert.deepStrictEqual(normalizeOrders({ orders: [{ symbol: "O" }] }).length, 1);
  assert.deepStrictEqual(normalizeTrades({ trades: [{ symbol: "T" }] }).length, 1);
  assert.deepStrictEqual(normalizeBlocked({ decisions: [{ symbol: "ARB/USD" }] }).length, 1);
  assert.deepStrictEqual(normalizeBlocked({ blocked: [{ symbol: "BTC" }] }).length, 1);

  const g = normalizeMemoryGraph({ status: "ok", nodes: [{ id: "1" }], edges: [] });
  assert.strictEqual(g.nodes.length, 1);
  assert.strictEqual(g.status, "ok");

  assert.deepStrictEqual(normalizeArrayResponse({ items: [1, 2] }, []), [1, 2]);

  console.log("verify_response_normalizers: OK");
}

run();
