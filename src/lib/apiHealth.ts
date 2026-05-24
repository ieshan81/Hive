import { apiGet, buildApiUrl } from "@/lib/apiClient";

export type EndpointProbe = {
  path: string;
  ok: boolean;
  status: number;
  url: string;
  contentType: string | null;
  rawKeys: string[];
  error: string | null;
  corsBlocked?: boolean;
  itemCount?: number;
};

const DASHBOARD_ENDPOINTS = [
  "/health",
  "/api/memory/graph",
  "/api/memory/lessons",
  "/api/decisions/latest",
  "/api/decisions/approved?cycle_run_id=latest",
  "/api/decisions/blocked?cycle_run_id=latest",
  "/api/positions",
  "/api/positions/state",
  "/api/orders",
  "/api/trades/history",
] as const;

function countItems(data: unknown): number | undefined {
  if (!data || typeof data !== "object") return undefined;
  const o = data as Record<string, unknown>;
  for (const key of [
    "nodes",
    "positions",
    "states",
    "orders",
    "trades",
    "blocked",
    "approved",
    "lessons",
    "decisions",
  ]) {
    if (Array.isArray(o[key])) return (o[key] as unknown[]).length;
  }
  if (Array.isArray(data)) return data.length;
  return undefined;
}

export async function probeApiEndpoints(): Promise<EndpointProbe[]> {
  const results: EndpointProbe[] = [];
  for (const path of DASHBOARD_ENDPOINTS) {
    const r = await apiGet(path);
    results.push({
      path,
      ok: r.ok,
      status: r.status,
      url: r.url,
      contentType: r.contentType,
      rawKeys: r.rawKeys,
      error: r.error,
      corsBlocked: r.corsBlocked,
      itemCount: countItems(r.data),
    });
  }
  return results;
}

export function logApiHealthToConsole(probes: EndpointProbe[]): void {
  const base = buildApiUrl("/");
  console.group("[Hive API Health]");
  console.log("API base:", base || "(relative /api via Next rewrite)");
  for (const p of probes) {
    const line = `${p.ok ? "OK" : "FAIL"} ${p.status} ${p.path} keys=[${p.rawKeys.join(",")}] count=${p.itemCount ?? "?"}`;
    if (p.ok) console.log(line);
    else console.warn(line, p.error, "url:", p.url);
  }
  console.groupEnd();
}

export const UI_PANEL_DATA_SOURCES = [
  { panel: "HiveMemoryGraphPanel", endpoints: ["/api/memory/graph", "/api/memory/node/{id}"] },
  { panel: "PositionsPage", endpoints: ["/api/positions", "/api/positions/state", "/api/trades/history", "/api/orders"] },
  { panel: "DecisionDrilldownModal", endpoints: ["/api/decisions/{type}?cycle_run_id=latest"] },
  { panel: "HiveMindSection", endpoints: ["/api/memory/hive-mind", "/api/memory/graph"] },
  { panel: "Dashboard (SSR)", endpoints: ["/api/dashboard"] },
] as const;
