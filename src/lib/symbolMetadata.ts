import { apiGet } from "@/lib/apiClient";

export type SymbolMetadata = {
  symbol: string;
  display_symbol?: string;
  normalized_symbol?: string;
  asset_class?: string;
  full_name?: string | null;
  venue?: string | null;
  exchange?: string | null;
  tradable?: boolean | null;
  session_type?: string | null;
  source?: string;
  last_price?: number | null;
  spread_pct?: number | null;
  latest_sentiment?: number | null;
  latest_trade_pnl?: number | null;
  latest_strategy?: string | null;
  metadata_stale?: boolean;
  missing_fields?: string[];
};

// Per-symbol cache so hovering doesn't refetch every mouse move.
const cache = new Map<string, SymbolMetadata>();
const inflight = new Map<string, Promise<SymbolMetadata | null>>();

export function cachedSymbolMetadata(symbol: string): SymbolMetadata | undefined {
  return cache.get((symbol || "").toUpperCase());
}

export async function fetchSymbolMetadata(symbol: string): Promise<SymbolMetadata | null> {
  const key = (symbol || "").toUpperCase();
  if (!key) return null;
  const hit = cache.get(key);
  if (hit) return hit;
  const pending = inflight.get(key);
  if (pending) return pending;

  const p = (async () => {
    try {
      const res = await apiGet<{ symbols?: SymbolMetadata[] }>(
        `/api/symbols/metadata?symbols=${encodeURIComponent(symbol)}`,
        { timeoutMs: 5000 }
      );
      const item = res.ok && res.data?.symbols?.[0] ? res.data.symbols[0] : null;
      if (item) cache.set(key, item);
      return item;
    } finally {
      inflight.delete(key);
    }
  })();
  inflight.set(key, p);
  return p;
}
