"use client";

import { cn } from "@/lib/utils";
import { formatDisplaySymbol } from "@/lib/assetIcons";
import { AssetIcon } from "@/components/ui/AssetIcon";

type Props = {
  symbol: string;
  assetClass?: string;
  size?: "sm" | "md";
  showIcon?: boolean;
  className?: string;
  labelClassName?: string;
};

/** Standard ticker row: real asset icon + normalized symbol (e.g. BTC/USD). Use everywhere a symbol is shown. */
export function TickerSymbol({
  symbol,
  assetClass,
  size = "sm",
  showIcon = true,
  className,
  labelClassName,
}: Props) {
  const display = formatDisplaySymbol(symbol);
  if (!display || display === "—") {
    return <span className={cn("text-slate-500", labelClassName)}>—</span>;
  }
  return (
    <span className={cn("inline-flex items-center gap-1.5 min-w-0", className)}>
      {showIcon && <AssetIcon symbol={display} assetClass={assetClass} size={size} />}
      <span className={cn("truncate", labelClassName)}>{display}</span>
    </span>
  );
}
