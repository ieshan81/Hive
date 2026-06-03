import { DiagnosticBundlePanel } from "@/components/panels/DiagnosticBundlePanel";

export default function DiagnosticsPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-white">Diagnostics</h1>
        <p className="mt-1 text-sm text-slate-400">What to send for analysis — latest bundle only unless forensic requested</p>
      </header>
      <DiagnosticBundlePanel />
    </div>
  );
}
