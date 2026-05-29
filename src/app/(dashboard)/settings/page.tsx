import { PaperSettingsPanel } from "@/components/panels/PaperSettingsPanel";
import { SettingsBrainMaintenance } from "@/components/panels/SettingsBrainMaintenance";
import { FastTrainingPanel } from "@/components/panels/FastTrainingPanel";

export default function SettingsPage() {
  return (
    <section className="max-w-4xl space-y-4">
      <PaperSettingsPanel />
      <details className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
        <summary className="cursor-pointer text-[11px] text-slate-400">
          Legacy settings (read-only paper config tools)
        </summary>
        <div className="mt-3 space-y-4">
          <FastTrainingPanel />
          <SettingsBrainMaintenance />
          <p className="text-xs text-slate-500">
            Strategy and risk config lives in the database (config_current). Environment
            variables cannot arm live trading.
          </p>
        </div>
      </details>
    </section>
  );
}
