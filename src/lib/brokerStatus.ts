import { apiGet } from "@/lib/apiClient";

type HealthPayload = {
  alpaca_connected?: boolean;
  warnings?: string[];
  paper_trading_only?: boolean;
};

/** Fast broker connectivity — uses /api/health (~1s), not the 15s+ dashboard build. */
export async function fetchAlpacaConnected(options?: {
  forServer?: boolean;
  timeoutMs?: number;
}): Promise<boolean> {
  const result = await apiGet<HealthPayload>("/api/health", {
    forServer: options?.forServer,
    timeoutMs: options?.timeoutMs ?? 6000,
  });
  if (!result.ok || !result.data) return false;
  const keysMissing = (result.data.warnings ?? []).some((w) =>
    w.toUpperCase().includes("ALPACA_API_KEY")
  );
  if (keysMissing) return false;
  return Boolean(result.data.alpaca_connected);
}
