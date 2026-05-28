"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import {
  baseSymbol,
  cryptoIconUrls,
  isLikelyCrypto,
  stockIconUrl,
  tickerAccent,
} from "@/lib/assetIcons";

interface AssetIconProps {
  symbol: string;
  assetClass?: string;
  size?: "sm" | "md";
  className?: string;
}

export function AssetIcon({ symbol, assetClass, size = "sm", className }: AssetIconProps) {
  const [sourceIndex, setSourceIndex] = useState(0);
  const [failed, setFailed] = useState(false);
  const base = baseSymbol(symbol);
  const crypto = isLikelyCrypto(symbol, assetClass);
  const dim = size === "md" ? "h-9 w-9" : "h-8 w-8";
  const text = size === "md" ? "text-[11px]" : "text-[10px]";

  const sources = useMemo(() => {
    if (crypto) return cryptoIconUrls(symbol);
    const stock = stockIconUrl(symbol);
    return stock ? [stock] : [];
  }, [crypto, symbol]);

  if (!failed && sources.length > 0 && sourceIndex < sources.length) {
    return (
      <span
        className={cn(
          "inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-white/5 ring-1 ring-white/10",
          dim,
          className
        )}
      >
        <img
          src={sources[sourceIndex]}
          alt={base}
          width={size === "md" ? 36 : 32}
          height={size === "md" ? 36 : 32}
          className="h-full w-full object-cover"
          onError={() => {
            if (sourceIndex + 1 < sources.length) {
              setSourceIndex((i) => i + 1);
            } else {
              setFailed(true);
            }
          }}
        />
      </span>
    );
  }

  const accent = tickerAccent(symbol);
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-bold text-white ring-1 ring-white/10",
        dim,
        text,
        className
      )}
      style={{ backgroundColor: `${accent}33`, color: accent }}
      aria-hidden
      title={symbol}
    >
      {base.slice(0, 3)}
    </span>
  );
}
