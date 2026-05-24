import { getDiagnosticBundleUrl } from "@/lib/dashboard";
import { EmptyState } from "@/components/ui/EmptyState";

export default function ReportsPage() {
  return (
    <section className="max-w-xl space-y-4">
      <article className="rounded-xl border border-white/10 bg-white/3 p-6">
        <h2 className="text-lg font-semibold text-white mb-2">Diagnostic Bundle</h2>
        <p className="text-sm text-slate-400 mb-4">
          Export all journals, config, radar, risk events, and system health. Run POST /api/cycle/run first to populate activity logs.
        </p>
        <a
          href={getDiagnosticBundleUrl()}
          className="inline-flex items-center rounded-lg border border-hive-cyan/30 bg-hive-cyan/10 px-4 py-2 text-sm font-medium text-hive-cyan hover:bg-hive-cyan/20"
        >
          Download Diagnostic Bundle
        </a>
      </article>
      <EmptyState message="Reports populate from real backend data after cycle runs" />
    </section>
  );
}
