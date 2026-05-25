import { SettingsBrainMaintenance } from "@/components/panels/SettingsBrainMaintenance";
import { FastTrainingPanel } from "@/components/panels/FastTrainingPanel";

export default function SettingsPage() {
  return (
    <section className="max-w-2xl space-y-4">
      <FastTrainingPanel />
      <SettingsBrainMaintenance />
      <p className="text-xs text-slate-500">
        Strategy and risk config lives in the database (config_current). Environment variables cannot arm live trading.
      </p>
    </section>
  );
}
