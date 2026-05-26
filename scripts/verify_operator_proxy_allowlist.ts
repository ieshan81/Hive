/**
 * Operator proxy allowlist + danger-zone confirmation (backend) smoke tests.
 * Run: npx tsx scripts/verify_operator_proxy_allowlist.ts
 */

import { isOperatorProxyPathAllowed } from "../src/lib/operatorProxyAllowlist";

function assert(cond: boolean, msg: string) {
  if (!cond) throw new Error(msg);
}

function testAllowlist() {
  assert(isOperatorProxyPathAllowed("/api/danger-zone/nuke-everything"), "nuke path allowed");
  assert(
    isOperatorProxyPathAllowed("/api/danger-zone/ready-for-live-cleanup"),
    "ready cleanup path allowed"
  );
  assert(!isOperatorProxyPathAllowed("/api/danger-zone/nuke-everything/preview"), "preview POST blocked");
  assert(!isOperatorProxyPathAllowed("/api/danger-zone/unknown"), "unknown danger path blocked");
  assert(!isOperatorProxyPathAllowed("/api/admin/wipe"), "unknown path blocked");
  assert(!isOperatorProxyPathAllowed("/api/settings/live-lock-tripwire"), "GET-style path blocked");
  assert(isOperatorProxyPathAllowed("/api/autonomous-paper-learning/tick"), "apl tick allowed");
  console.log("OK allowlist");
}

async function testBackendConfirmation() {
  const base =
    process.env.API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "https://hive-production-7343.up.railway.app";
  const secret = process.env.OPERATOR_SECRET?.trim();
  if (!secret) {
    console.log("SKIP backend confirmation tests (OPERATOR_SECRET not set locally)");
    return;
  }
  const headers = {
    "Content-Type": "application/json",
    "X-Operator-Token": secret,
  };
  const wrongNuke = await fetch(`${base}/api/danger-zone/nuke-everything`, {
    method: "POST",
    headers,
    body: JSON.stringify({ confirmation: "WRONG" }),
  });
  const wrongBody = (await wrongNuke.json()) as { status?: string; reason?: string };
  assert(wrongNuke.status === 200, "nuke wrong phrase returns 200 with refused body");
  assert(wrongBody.status === "refused", "nuke wrong phrase refused");
  assert(wrongBody.reason === "confirmation_phrase_mismatch", "nuke mismatch reason");

  const lock = await fetch(`${base}/api/settings/live-lock-tripwire`);
  const lockBody = (await lock.json()) as { live_lock_status?: string; live_trading_enabled?: boolean };
  assert(lockBody.live_lock_status === "locked", "live lock remains locked");
  assert(lockBody.live_trading_enabled === false, "live trading not enabled");
  console.log("OK backend confirmation + live lock");
}

async function testProductionProxy(secretFromEnv: boolean) {
  const fe =
    process.env.FRONTEND_URL || "https://melodious-happiness-production-0f5b.up.railway.app";
  const probe = await fetch(`${fe}/operator-proxy`, { cache: "no-store" });
  const probeBody = (await probe.json()) as Record<string, unknown>;
  assert(probeBody.server_operator_auth_configured === true, "proxy configured");
  const bodyStr = JSON.stringify(probeBody);
  assert(!bodyStr.includes("OPERATOR_SECRET="), "probe does not expose secret value");

  const wrongPath = await fetch(`${fe}/operator-proxy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: "/api/danger-zone/unknown", body: {} }),
  });
  const wp = (await wrongPath.json()) as { status?: string };
  assert(wrongPath.status === 403 && wp.status === "forbidden", "unknown path forbidden");

  const nukeWrong = await fetch(`${fe}/operator-proxy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      path: "/api/danger-zone/nuke-everything",
      body: { confirmation: "WRONG" },
    }),
  });
  const nw = (await nukeWrong.json()) as { status?: string; reason?: string };
  assert(nukeWrong.status === 200, "nuke via proxy reaches backend");
  assert(nw.status === "refused", "wrong phrase refused not proxy forbidden");
  assert(nw.reason === "confirmation_phrase_mismatch", "confirmation error from backend");

  const readyWrong = await fetch(`${fe}/operator-proxy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      path: "/api/danger-zone/ready-for-live-cleanup",
      body: { confirmation: "WRONG" },
    }),
  });
  const rw = (await readyWrong.json()) as { status?: string; reason?: string };
  assert(readyWrong.status === 200, "ready cleanup via proxy reaches backend");
  assert(rw.status === "refused", "ready wrong phrase refused");

  if (!secretFromEnv) {
    console.log("OK production proxy (allowlist + wrong phrase via live frontend)");
  }
}

async function main() {
  testAllowlist();
  await testBackendConfirmation();
  await testProductionProxy(false);
  console.log("ALL OPERATOR PROXY ALLOWLIST CHECKS PASSED");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
