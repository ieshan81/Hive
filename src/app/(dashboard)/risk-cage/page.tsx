import { RiskCagePanel } from "@/components/panels/RiskCagePanel";

export default function RiskCagePage() {
  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <header>
        <h1 className="text-2xl font-bold text-white">Risk Cage</h1>
        <p className="mt-1 text-sm text-slate-400">Why execution is blocked or allowed</p>
      </header>
      <RiskCagePanel />
    </div>
  );
}
