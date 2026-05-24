/**
 * Verify API URL building (run: npx tsx scripts/verify_frontend_api_client.ts)
 */
import assert from "node:assert";
import { buildApiUrl, getApiBaseUrl } from "../src/lib/apiClient";

function run() {
  const serverBase = getApiBaseUrl({ forServer: true });
  assert.ok(serverBase.includes("railway.app") || serverBase.includes("localhost"), "server base set");

  const rel = buildApiUrl("/api/positions", false);
  assert.strictEqual(rel, "/api/positions", "browser uses relative path");

  const abs = buildApiUrl("/api/positions", true);
  assert.ok(abs.startsWith("http"), "server uses absolute URL");
  assert.ok(abs.endsWith("/api/positions"), "path appended");

  console.log("verify_frontend_api_client: OK");
}

run();
