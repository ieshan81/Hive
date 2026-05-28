"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Brain,
  TrendingUp,
  Globe,
  Wallet,
  BarChart3,
  Activity,
  FileText,
  Settings,
  Shield,
  Hexagon,
  Terminal,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchAlpacaConnected } from "@/lib/brokerStatus";

// Stitch design system — Caged Hive cockpit nav
// Surface: surface-container-lowest (#0d0e12) with backdrop-blur
// Active state: cyan left-accent + faint cyan tint + tactical-green status border

const navItems = [
  { href: "/", label: "Mission Control", icon: LayoutDashboard },
  { href: "/universe", label: "Universe Radar", icon: Globe },
  { href: "/push-pull", label: "Push-Pull Trader", icon: TrendingUp },
  { href: "/ai-manager", label: "AI Manager", icon: Brain },
  { href: "/portfolio", label: "Portfolio", icon: Wallet },
  { href: "/performance", label: "Performance", icon: BarChart3 },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/control-center", label: "Control Center", icon: Settings },
];

const utilityItems = [
  { href: "/control-center#security", label: "Security", icon: ShieldCheck },
  { href: "/control-center#system-log", label: "System Log", icon: Terminal },
];

interface SidebarProps {
  systemStatus?: { alpacaConnected: boolean; paperTradingOnly: boolean };
}

export function Sidebar({ systemStatus }: SidebarProps) {
  const pathname = usePathname();
  const [alpacaProof, setAlpacaProof] = useState<boolean | null>(null);
  const alpacaConnected = Boolean(systemStatus?.alpacaConnected || alpacaProof);

  useEffect(() => {
    let cancelled = false;
    async function loadBrokerProof() {
      const connected = await fetchAlpacaConnected({ timeoutMs: 6000 });
      if (!cancelled) setAlpacaProof(connected);
    }
    loadBrokerProof();
    const t = setInterval(loadBrokerProof, 30000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  return (
    <aside
      className="fixed left-0 top-0 z-40 flex h-screen w-[240px] flex-col border-r border-white/[0.06] backdrop-blur-xl"
      style={{ backgroundColor: "#0d0e12" }}
    >
      {/* Brand */}
      <div className="px-4 pt-5 pb-6 border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <div className="relative flex h-9 w-9 items-center justify-center rounded-lg bg-[#00f0ff]/10 border border-[#00dbe9]/30">
            <Hexagon
              className="absolute h-9 w-9 text-[#00dbe9]"
              strokeWidth={1.3}
              style={{ filter: "drop-shadow(0 0 8px rgba(0,219,233,0.4))" }}
            />
            <Brain className="relative h-4 w-4 text-[#00dbe9]" strokeWidth={2} />
          </div>
          <div>
            <h1 className="text-[18px] font-bold tracking-tight text-[#00dbe9] leading-none">
              Caged Hive
            </h1>
            <p className="label-caps text-[#b9cacb] opacity-70 mt-1">
              Institutional Cockpit
            </p>
          </div>
        </div>
      </div>

      {/* Primary nav */}
      <nav className="flex-1 overflow-y-auto scrollbar-thin px-2 py-3 space-y-0.5">
        {navItems.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "group relative flex items-center gap-3 rounded-lg px-3 py-2 transition-all duration-200",
                isActive
                  ? "text-[#dbfcff] bg-[#00f0ff]/5"
                  : "text-[#b9cacb] hover:text-[#dbfcff] hover:bg-white/[0.04]"
              )}
            >
              {isActive && (
                <span
                  className="absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-r"
                  style={{
                    background: "#00FF66",
                    boxShadow: "0 0 8px rgba(0, 255, 102, 0.5)",
                  }}
                />
              )}
              <Icon
                className={cn("h-[18px] w-[18px] flex-shrink-0", isActive && "text-[#00dbe9]")}
                strokeWidth={1.75}
              />
              <span className="label-caps">{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Utility */}
      <div className="px-2 py-3 border-t border-white/[0.06] space-y-0.5">
        {utilityItems.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-[#b9cacb] hover:text-[#dbfcff] hover:bg-white/[0.04] transition-all"
          >
            <Icon className="h-[18px] w-[18px] flex-shrink-0" strokeWidth={1.75} />
            <span className="label-caps">{label}</span>
          </Link>
        ))}
      </div>

      {/* System integrity card */}
      <div className="mx-3 mb-4 mt-2 rounded-xl border p-3"
           style={{
             borderColor: alpacaConnected ? "rgba(0, 255, 102, 0.25)" : "rgba(245, 158, 11, 0.25)",
             backgroundColor: alpacaConnected ? "rgba(0, 255, 102, 0.04)" : "rgba(245, 158, 11, 0.04)",
           }}
      >
        <div className="flex items-center gap-2 mb-1.5">
          <Shield
            className="h-3.5 w-3.5"
            style={{ color: alpacaConnected ? "#00FF66" : "#F59E0B" }}
          />
          <span className="label-caps text-[#b9cacb]">System Integrity</span>
        </div>
        <p
          className="text-xl font-bold mono-metric"
          style={{ color: alpacaConnected ? "#00FF66" : "#F59E0B" }}
        >
          {alpacaConnected ? "ONLINE" : "OFFLINE"}
        </p>
        <p
          className="text-[10px] mt-0.5"
          style={{ color: alpacaConnected ? "rgba(0, 255, 102, 0.75)" : "rgba(245, 158, 11, 0.75)" }}
        >
          {alpacaConnected ? "Alpaca paper connected" : "Waiting for Alpaca sync"}
        </p>
        <p className="text-[9px] text-[#849495] mt-1">
          Paper trading only · Live locked
        </p>
      </div>
    </aside>
  );
}
