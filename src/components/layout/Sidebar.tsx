"use client";

import {
  LayoutDashboard,
  Brain,
  FlaskConical,
  Radar,
  Lock,
  LineChart,
  TrendingUp,
  FileText,
  Settings,
  Shield,
  Hexagon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { NavItemId } from "@/types/dashboard";

const navItems: { id: NavItemId; label: string; icon: React.ElementType }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "ai-manager", label: "AI Manager", icon: Brain },
  { id: "strategies", label: "Strategies", icon: FlaskConical },
  { id: "market-radar", label: "Market Radar", icon: Radar },
  { id: "risk-cage", label: "Risk Cage", icon: Lock },
  { id: "backtesting", label: "Backtesting", icon: LineChart },
  { id: "performance", label: "Performance", icon: TrendingUp },
  { id: "reports", label: "Reports", icon: FileText },
  { id: "settings", label: "Settings", icon: Settings },
];

interface SidebarProps {
  activeId?: NavItemId;
  systemStatus?: { alpacaConnected: boolean; paperTradingOnly: boolean };
}

export function Sidebar({ activeId = "overview", systemStatus }: SidebarProps) {
  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-[220px] flex-col border-r border-white/5 bg-[rgba(5,7,10,0.95)] backdrop-blur-xl">
      <div className="flex items-center gap-3 px-5 py-6 border-b border-white/5">
        <div className="relative flex h-10 w-10 items-center justify-center">
          <Hexagon
            className="absolute h-10 w-10 text-hive-cyan"
            strokeWidth={1.5}
            style={{ filter: "drop-shadow(0 0 12px rgba(0,209,255,0.5))" }}
          />
          <Brain className="relative h-4 w-4 text-hive-cyan" strokeWidth={2} />
        </div>
        <div>
          <p className="text-xs font-bold tracking-wider text-white">HIVE</p>
          <p className="text-[9px] text-slate-500 tracking-widest">QUANT</p>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto scrollbar-thin px-3 py-4 space-y-0.5">
        {navItems.map(({ id, label, icon: Icon }) => {
          const isActive = id === activeId;
          return (
            <button
              key={id}
              type="button"
              className={cn(
                "relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-all",
                isActive
                  ? "bg-hive-cyan/10 text-hive-cyan"
                  : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
              )}
            >
              {isActive && (
                <span className="absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-r bg-hive-cyan shadow-[0_0_8px_rgba(0,209,255,0.6)]" />
              )}
              <Icon className="h-4 w-4 flex-shrink-0" strokeWidth={1.75} />
              <span className="truncate font-medium">{label}</span>
            </button>
          );
        })}
      </nav>

      <div className="mx-3 mb-4 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
        <div className="flex items-center gap-2 mb-1">
          <Shield className="h-4 w-4 text-emerald-400" />
          <span className="text-[10px] font-semibold tracking-wider text-slate-400 uppercase">
            System Integrity
          </span>
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
