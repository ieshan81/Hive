import assert from "node:assert";
import { normalizeMemoryGraph } from "../src/lib/apiNormalize";

/** Simulates successful graph response — panel should not treat as empty. */
function run() {
  const ok = normalizeMemoryGraph({
    status: "ok",
    nodes: [
      { id: "lesson-5", label: "L5", type: "lesson", x: 0, y: 0 },
      { id: "hive", label: "HIVE", type: "center", x: 50, y: 50 },
    ],
    edges: [{ id: "e1", source: "lesson-5", target: "hive", relation: "feeds" }],
  });
  assert.ok(ok.nodes.length >= 1, "nodes present after normalize");
  const lessons = ok.nodes.filter((n) => n.type === "lesson" || n.id.startsWith("lesson-"));
  assert.ok(lessons.length >= 1, "lesson nodes renderable");

  const fail = normalizeMemoryGraph(null);
  assert.strictEqual(fail.nodes.length, 0, "null → empty graph for error UI");

  console.log("verify_memory_graph_fetch: OK");
}

run();
