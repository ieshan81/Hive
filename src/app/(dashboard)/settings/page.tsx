import { EmptyState } from "@/components/ui/EmptyState";

export default function SettingsPage() {
  return (
    <section className="max-w-xl">
      <EmptyState message="Strategy and risk config lives in the database (config_current). Use the API config manager — not env vars." />
    </section>
  );
}
