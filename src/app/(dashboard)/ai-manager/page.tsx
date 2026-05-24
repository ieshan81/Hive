"use client";

import { useEffect, useState } from "react";
import { AIFundManagerPanel } from "@/components/panels/AIFundManagerPanel";
import { HiveMindSection } from "@/components/panels/HiveMindSection";
import type { AIFundManagerData } from "@/types/dashboard";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function AIManagerPage() {
  const [ai, setAi] = useState<AIFundManagerData | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/dashboard`)
      .then((r) => r.json())
      .then((d) => setAi(d.aiFundManager))
      .catch(() => setAi(null));
  }, []);

  if (!ai) {
    return <p className="text-slate-500 text-sm">Loading AI Manager…</p>;
  }

  return (
    <section className="max-w-4xl">
      <AIFundManagerPanel data={ai} />
      <HiveMindSection />
    </section>
  );
}
