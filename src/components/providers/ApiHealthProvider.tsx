"use client";

import { useEffect } from "react";
import { logApiHealthToConsole, probeApiEndpoints } from "@/lib/apiHealth";

/** Runs API health probes on mount and logs to browser console (dev + prod debugging). */
export function ApiHealthProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    probeApiEndpoints().then(logApiHealthToConsole);
  }, []);
  return <>{children}</>;
}
