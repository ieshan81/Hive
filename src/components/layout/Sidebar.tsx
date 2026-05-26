"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Brain,
  FlaskConical,
  LineChart,
  TrendingUp,
  FileText,
  Wallet,
  Settings,
  Shield,
  Hexagon,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Mission Control", icon: LayoutDashboard },
  { href: "/ai-manager", label: "AI Manager", icon: Brain },
  { href: "/push-pull", label: "Push-Pull Trader", icon: TrendingUp },
  { href: "/portfolio", label: "Portfolio & Execution", icon: Wallet },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/danger-zone", label: "Danger Zone", icon: Shield },
];

/** Legacy routes — still reachable via URL for advanced tools */
const legacyHidden = false;
const legacyNav = legacyHidden
  ? []
  : [
      { href: "/strategies", label: "Strategies (legacy)", icon: FlaskConical },
      { href: "/backtesting", label: "Backtesting (legacy)", icon: LineChart },
    ];

interface SidebarProps {
  systemStatus?: { alpacaConnected: boolean; paperTradingOnly: boolean };
}

export function Sidebar({ systemStatus }: SidebarProps) {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-[220px] flex-col border-r border-white/5 bg-[rgba(5,7,10,0.95)] backdrop-blur-xl">
      <div className="flex items-center gap-3 px-5 py-6 border-b border-white/5">
        <div className="relative flex h-10 w-10 items-center justify-center">
          <Hexagon className="absolute h-10 w-10 text-hive-cyan" strokeWidth={1.5} style={{ filter: "drop-shadow(0 0 12px rgba(0,209,255,0.5))" }} />
          <Brain className="relative h-4 w-4 text-hive-cyan" strokeWidth={2} />
        </div>
        <div>
          <p className="text-xs font-bold tracking-wider text-white">HIVE</p>
          <p className="text-[9px] text-slate-500 tracking-widest">QUANT</p>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto scrollbar-thin px-3 py-4 space-y-0.5">
        {[...navItems, ...legacyNav].map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all",
                isActive ? "bg-hive-cyan/10 text-hive-cyan" : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
              )}
            >
              {isActive && (
                <span className="absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-r bg-hive-cyan shadow-[0_0_8px_rgba(0,209,255,0.6)]" />
              )}
              <Icon className="h-4 w-4 flex-shrink-0" strokeWidth={1.75} />
              <span className="truncate font-medium">{label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="mx-3 mb-4 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
        <div className="flex items-center gap-2 mb-1">
          <Shield className="h-4 w-4 text-emerald-400" />
          <span className="text-[10px] font-semibold tracking-wider text-slate-400 uppercase">System Integrity</span>
        </div>
        <p className="text-2xl font-bold text-emerald-400">{systemStatus?.alpacaConnected ? "ONLINE" : "OFFLINE"}</p>
        <p className="text-[10px] text-emerald-400/80 mt-0.5">
          {systemStatus?.alpacaConnected ? "Alpaca paper connected" : "Waiting for Alpaca sync"}
        </p>
        <p className="text-[9px] text-slate-500 mt-1">Paper trading only · Live disabled</p>
      </div>
    </aside>
  );
}
