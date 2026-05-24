"use client";

import { Lock } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import type { RiskRule } from "@/types/dashboard";

interface RiskCagePanelProps {
  rules: RiskRule[];
}

export function RiskCagePanel({ rules }: RiskCagePanelProps) {
  return (
    <GlassPanel
      title="Risk Cage"
      icon={<Lock className="h-4 w-4" />}
      subtitle="Rules are Unbreakable."
    >
      <ul className="space-y-2 mb-4">
        {rules.map((rule) => (
          <li
            key={rule.id}
            className="flex items-center justify-between gap-3 rounded-lg border border-white/4 bg-white/2 px-3 py-2"
          >
            <span className="text-xs text-slate-300 flex-1">{rule.text}</span>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="rounded px-1.5 py-0.5 text-[8px] font-bold tracking-wider bg-hive-cyan/15 text-hive-cyan border border-hive-cyan/25">
                ENFORCED
              </span>
              <Lock className="h-3 w-3 text-slate-500" />
            </div>
          </li>
        ))}
      </ul>

      <div className="flex items-center justify-center gap-2 pt-2 border-t border-white/5">
        <Lock className="h-3.5 w-3.5 text-hive-cyan" />
        <p className="text-xs text-hive-cyan/80">The cage protects the mission.</p>
      </div>
    </GlassPanel>
  );
}
