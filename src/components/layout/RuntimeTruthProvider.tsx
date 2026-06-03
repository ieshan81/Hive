"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { fetchRuntimeTruth, type RuntimeTruth } from "@/lib/runtimeTruth";

type RuntimeTruthContextValue = {
  truth: RuntimeTruth | null;
  loading: boolean;
  degraded: boolean;
  refresh: () => void;
};

const RuntimeTruthContext = createContext<RuntimeTruthContextValue>({
  truth: null,
  loading: true,
  degraded: false,
  refresh: () => {},
});

export function RuntimeTruthProvider({
  initial,
  children,
}: {
  initial?: RuntimeTruth | null;
  children: ReactNode;
}) {
  const [truth, setTruth] = useState<RuntimeTruth | null>(initial ?? null);
  const [loading, setLoading] = useState(!initial);
  const [degraded, setDegraded] = useState(false);
  const truthRef = useRef(truth);
  truthRef.current = truth;

  const refresh = useCallback(async () => {
    const res = await fetchRuntimeTruth({ timeoutMs: 15000 });
    if (res.ok && res.data) {
      setTruth(res.data);
      setDegraded(Boolean(res.data.data_degraded));
    } else if (truthRef.current) {
      // Keep last good snapshot — transient timeout must not flash false offline states.
      setDegraded(true);
    } else {
      setDegraded(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <RuntimeTruthContext.Provider value={{ truth, loading, degraded, refresh }}>
      {children}
    </RuntimeTruthContext.Provider>
  );
}

export function useRuntimeTruth() {
  return useContext(RuntimeTruthContext);
}
