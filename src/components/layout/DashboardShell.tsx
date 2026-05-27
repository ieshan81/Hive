"use client";

import { ApiHealthProvider } from "@/components/providers/ApiHealthProvider";
import { NeuralBackdrop } from "@/components/layout/NeuralBackdrop";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  return (
    <ApiHealthProvider>
      <NeuralBackdrop />
      {children}
    </ApiHealthProvider>
  );
}
