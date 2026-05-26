/** Symbol display identity — icons and labels for universe / radar. */

const CRYPTO: Record<string, { glyph: string; name: string }> = {
  "BTC/USD": { glyph: "₿", name: "Bitcoin" },
  "ETH/USD": { glyph: "Ξ", name: "Ethereum" },
  "SOL/USD": { glyph: "◎", name: "Solana" },
  "DOGE/USD": { glyph: "Ð", name: "Dogecoin" },
  "AVAX/USD": { glyph: "A", name: "Avalanche" },
  "LINK/USD": { glyph: "⬡", name: "Chainlink" },
  "LTC/USD": { glyph: "Ł", name: "Litecoin" },
  "UNI/USD": { glyph: "U", name: "Uniswap" },
};

const STOCKS: Record<string, { glyph: string; name: string }> = {
  NVDA: { glyph: "N", name: "Nvidia" },
  AAPL: { glyph: "", name: "Apple" },
  MSFT: { glyph: "M", name: "Microsoft" },
  TSLA: { glyph: "T", name: "Tesla" },
  AMD: { glyph: "A", name: "AMD" },
  META: { glyph: "f", name: "Meta" },
  AMZN: { glyph: "a", name: "Amazon" },
  GOOGL: { glyph: "G", name: "Alphabet" },
  SPY: { glyph: "ETF", name: "S&P 500 ETF" },
  QQQ: { glyph: "ETF", name: "Nasdaq ETF" },
};

export function symbolIdentity(symbol: string): { glyph: string; name: string; badge: string } {
  const c = CRYPTO[symbol];
  if (c) return { ...c, badge: "Crypto" };
  const s = STOCKS[symbol];
  if (s) return { ...s, badge: s.glyph === "ETF" ? "ETF" : "Stock" };
  if (symbol.includes("/")) return { glyph: symbol.split("/")[0]?.slice(0, 2) ?? "?", name: symbol, badge: "Crypto" };
  return { glyph: symbol.slice(0, 2), name: symbol, badge: "Stock" };
}
