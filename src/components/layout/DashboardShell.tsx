"use client";

import { ApiHealthProvider } from "@/components/providers/ApiHealthProvider";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  return <ApiHealthProvider>{children}</ApiHealthProvider>;
}
