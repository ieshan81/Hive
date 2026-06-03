import { HiveMindSection } from "@/components/panels/HiveMindSection";

export default function EvidenceMemoryPage() {
  return (
    <section className="mx-auto max-w-4xl space-y-4">
      <header>
        <h1 className="text-2xl font-bold text-white">Evidence Memory</h1>
        <p className="mt-1 text-sm text-slate-400">Blocker history, lessons, and scorecard evidence — advisory only</p>
      </header>
      <HiveMindSection />
    </section>
  );
}
