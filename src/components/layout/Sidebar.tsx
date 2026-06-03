"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Globe,
  FileText,
  Hexagon,
  LineChart,
  Settings as SettingsIcon,
  Shield,
  Sparkles,
  Target,
  Wallet,
  Workflow,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { brokerLabel } from "@/lib/runtimeTruth";
import { useRuntimeTruth } from "@/components/layout/RuntimeTruthProvider";

const primaryNav = [
  { href: "/mission-control", label: "Mission Control", icon: Activity },
  { href: "/universe", label: "Universe", icon: Globe },
  { href: "/shadow-league", label: "Shadow League", icon: Sparkles },
  { href: "/paper-candidates", label: "Paper Candidates", icon: Target },
  { href: "/risk-cage", label: "Risk Cage", icon: Shield },
  { href: "/evidence-memory", label: "Evidence Memory", icon: Sparkles },
  { href: "/diagnostics", label: "Diagnostics", icon: FileText },
];

const operatorNav = [
  { href: "/portfolio", label: "Portfolio", icon: Wallet },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
  { href: "/engine-map", label: "Engine map", icon: Workflow },
  { href: "/tradingview", label: "TradingView", icon: LineChart },
];

interface SidebarProps {
  systemStatus?: { alpacaConnected: boolean; paperTradingOnly: boolean; paperBroker?: boolean };
}

export function Sidebar({ systemStatus }: SidebarProps) {
  const pathname = usePathname();
  const { truth, degraded, loading } = useRuntimeTruth();
  const paperOk = Boolean(
    truth?.broker_connected ||
      truth?.paper_broker ||
      (truth?.paper_broker && truth?.paper_orders_enabled) ||
      systemStatus?.paperBroker ||
      systemStatus?.alpacaConnected
  );
  const label = loading && !truth ? "Loading…" : truth ? brokerLabel(truth, degraded) : "Loading…";
  const color =
    paperOk || truth?.paper_broker ? "#00FF66" : loading ? "#94A3B8" : degraded ? "#F59E0B" : "#F59E0B";

  return (
    <aside
      className="fixed left-0 top-0 z-40 flex h-screen w-[220px] flex-col border-r border-white/[0.06] backdrop-blur-xl"
      style={{ backgroundColor: "#0d0e12" }}
    >
      <div className="border-b border-white/[0.06] px-4 pb-5 pt-5">
        <div className="flex items-center gap-3">
          <div className="relative flex h-9 w-9 items-center justify-center rounded-lg border border-[#00dbe9]/30 bg-[#00f0ff]/10">
            <Hexagon className="absolute h-9 w-9 text-[#00dbe9]" strokeWidth={1.3} />
            <Activity className="relative h-4 w-4 text-[#00dbe9]" strokeWidth={2} />
          </div>
          <div>
            <h1 className="text-[17px] font-bold leading-none tracking-tight text-[#00dbe9]">Caged Hive</h1>
            <p className="label-caps mt-1 text-[#b9cacb] opacity-70">Paper validation lab</p>
          </div>
        </div>
      </div>

      <nav className="scrollbar-thin flex-1 space-y-0.5 overflow-y-auto px-2 py-3">
        {primaryNav.map(({ href, label: navLabel, icon: Icon }) => {
          const isActive = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all",
                isActive ? "bg-[#00f0ff]/5 text-[#dbfcff]" : "text-[#b9cacb] hover:bg-white/[0.04] hover:text-[#dbfcff]"
              )}
            >
              {isActive && (
                <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r bg-[#00FF66]" />
              )}
              <Icon className={cn("h-4 w-4 shrink-0", isActive && "text-[#00dbe9]")} strokeWidth={1.75} />
              <span>{navLabel}</span>
            </Link>
          );
        })}
        <p className="label-caps mb-1 mt-4 px-3 text-[#849495]">Operator</p>
        {operatorNav.map(({ href, label: navLabel, icon: Icon }) => {
          const isActive = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-1.5 text-xs transition-all",
                isActive ? "text-[#dbfcff]" : "text-[#849495] hover:text-[#b9cacb]"
              )}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span>{navLabel}</span>
            </Link>
          );
        })}
      </nav>

      <div
        className="mx-3 mb-4 rounded-xl border p-3"
        style={{
          borderColor: paperOk ? "rgba(0, 255, 102, 0.25)" : "rgba(245, 158, 11, 0.25)",
          backgroundColor: paperOk ? "rgba(0, 255, 102, 0.04)" : "rgba(245, 158, 11, 0.04)",
        }}
      >
        <div className="mb-1 flex items-center gap-2">
          <Shield className="h-3.5 w-3.5" style={{ color }} />
          <span className="text-[10px] uppercase text-[#b9cacb]">Broker</span>
        </div>
        <p className="mono-metric text-lg font-bold" style={{ color }}>
          {label}
        </p>
        <p className="mt-1 text-[9px] text-[#849495]">
          {truth?.live_locked === false ? "Live check" : "Live locked"} · paper only
        </p>
      </div>
    </aside>
  );
}
