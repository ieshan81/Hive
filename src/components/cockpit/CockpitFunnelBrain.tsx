"use client";

type Props = {
  funnel?: Record<string, number>;
  blockers?: string;
  aiNote?: string;
};

const STAGES = [
  ["available", "Available"],
  ["cached", "Cached"],
  ["fresh", "Fresh"],
  ["eligible", "Eligible"],
  ["ranked", "Ranked"],
  ["shortlist", "To trade"],
] as const;

function formatBlockers(raw?: string, funnel?: Record<string, number>): string | undefined {
  if (!raw) return undefined;
  const avail = Number(funnel?.available ?? 0);
  const fresh = Number(funnel?.fresh ?? 0);
  if (avail > 0 && fresh === 0 && /stale_bar:\s*\d+/.test(raw)) {
    return `${raw} — bars may need refresh; scoring uses cached history when within staleness window.`;
  }
  if (/insufficient_historical_bars/.test(raw)) {
    return `${raw} — run market data refresh or wait for the next scheduler tick.`;
  }
  return raw;
}

export function CockpitFunnelBrain({ funnel, blockers, aiNote }: Props) {
  const f = funnel ?? {};
  const blockerText = formatBlockers(blockers, f);
  const showAiNote = aiNote && aiNote !== blockerText;

  return (
    <div className="rounded-xl border border-violet-500/20 bg-violet-950/10 p-4">
      <p className="text-[10px] uppercase tracking-wider text-violet-300/80 mb-3">Scan funnel · 6 stages</p>
      <div className="flex flex-wrap items-center gap-1 md:gap-2">
        {STAGES.map(([key, label], i) => (
          <div key={key} className="flex items-center gap-1">
            <div className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 min-w-[52px] text-center">
              <p className="text-[8px] text-slate-500 uppercase">{label}</p>
              <p className="text-sm font-bold text-white mono-metric">{String(f[key] ?? 0)}</p>
            </div>
            {i < STAGES.length - 1 && <span className="text-slate-600 text-xs">→</span>}
          </div>
        ))}
      </div>
      {blockerText && (
        <p className="text-[10px] text-amber-300/90 mt-3 border-t border-white/5 pt-2">
          Cage blockers: {blockerText}
        </p>
      )}
      {showAiNote && <p className="text-[10px] text-cyan-200/80 mt-2">{aiNote}</p>}
    </div>
  );
}
