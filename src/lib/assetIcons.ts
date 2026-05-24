/** Extract base ticker for icon lookup (ETH/USD → ETH, AAPL → AAPL). */
export function baseSymbol(symbol: string): string {
  const s = symbol.trim().toUpperCase();
  if (s.includes("/")) return s.split("/")[0];
  if (s.endsWith("USD") && s.length > 3) return s.slice(0, -3);
  if (s.endsWith("USDC") && s.length > 4) return s.slice(0, -4);
  if (s.endsWith("USDT") && s.length > 4) return s.slice(0, -4);
  return s;
}

const CRYPTO_ICON_BASE =
  "https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@master/32/color";

export function cryptoIconUrl(symbol: string): string {
  return `${CRYPTO_ICON_BASE}/${baseSymbol(symbol).toLowerCase()}.png`;
}

/** Brand-ish accent colors for known tickers when icon fails. */
const TICKER_COLORS: Record<string, string> = {
  BTC: "#F7931A",
  ETH: "#627EEA",
  SOL: "#9945FF",
  DOGE: "#C2A633",
  AAVE: "#B6509E",
  DOT: "#E6007A",
  ARB: "#28A0F0",
  BCH: "#8DC351",
  AAPL: "#A2AAAD",
  MSFT: "#00A4EF",
  NVDA: "#76B900",
  TSLA: "#CC0000",
  SPY: "#4ADE80",
};

export function tickerAccent(symbol: string): string {
  const base = baseSymbol(symbol);
  return TICKER_COLORS[base] ?? (base.length > 0 ? "#64748b" : "#475569");
}

export function isLikelyCrypto(symbol: string, assetClass?: string): boolean {
  if (assetClass === "crypto") return true;
  if (assetClass === "stock") return false;
  const s = symbol.toUpperCase();
  return s.includes("/") || s.endsWith("USD") || s.endsWith("USDC") || s.endsWith("USDT");
}
