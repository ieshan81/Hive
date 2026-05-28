"use client";

import { useEffect, useState } from "react";
import { Settings, Shield, Wrench } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { DangerZonePanel } from "@/components/panels/DangerZonePanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";
import { EmptyState } from "@/components/ui/EmptyState";

type ControlCenterStatus = {
  system_state?: Record<string, string | boolean>;
  risk_cage?: Record<string, number>;
  strategy_parameters?: Record<string, number>;
  operator_actions?: { label: string; endpoint: string }[];
};

function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

export function ControlCenterPanel() {
  const [data, setData] = useState<ControlCenterStatus | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void apiGet<Record<string, unknown>>("/api/cockpit", { timeoutMs: 90000 }).then((res) => {
      if (res.ok && res.data) {
        const c = res.data;
        const ctrl = (c.control as Record<string, unknown>) || {};
        const w = (c.weights as Record<string, unknown>) || {};
        setData({
          system_state: {
            paper_learning: Boolean(ctrl.paper_learning_on),
            bot_can_place: Boolean(ctrl.bot_can_place),
            mode: String(ctrl.mode || "paper"),
            live_locked: true,
          },
          strategy_parameters: (w.universe_ranking as Record<string, number>) || {},
          operator_actions: [
            { label: "Hard rebuild", endpoint: "/api/rebuild" },
            { label: "Agent cycle", endpoint: "/api/agent/cycle" },
          ],
        });
      }
    });
  }, []);

  async function repairBootstrap() {
    if (!window.confirm("Run database bootstrap repair? This does not unlock live trading.")) return;
    setBusy(true);
    setMsg(null);
    const res = await apiPostOperator("/api/admin/repair-database-bootstrap", {});
    setBusy(false);
    setMsg(res.ok ? "Database bootstrap repair completed." : res.error ?? "Repair failed");
  }

  if (!data) return <EmptyState message="Loading Control Center…" className="min-h-[200px]" />;

  const sys = data.system_state ?? {};
  const risk = data.risk_cage ?? {};
  const params = data.strategy_parameters ?? {};

  return (
    <section className="max-w-4xl space-y-4">
      <div className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <Settings className="h-6 w-6 text-hive-cyan" />
          Control Center
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Operator controls for paper learning, risk settings, and diagnostics. Live trading remains locked.
        </p>
      </div>

      <GlassPanel title="System State" icon={<Shield className="h-4 w-4" />}>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          {Object.entries(sys).map(([k, v]) => (
            <div key={k}>
              <dt className="text-slate-500">{humanize(k)}</dt>
              <dd className="text-white font-medium">{String(v)}</dd>
            </div>
          ))}
        </dl>
      </GlassPanel>

      <GlassPanel title="Risk Cage" icon={<Shield className="h-4 w-4" />}>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          {Object.entries(risk).map(([k, v]) => (
            <div key={k}>
              <dt className="text-slate-500">{humanize(k)}</dt>
              <dd className="text-white">{String(v)}</dd>
            </div>
          ))}
        </dl>
      </GlassPanel>

      <GlassPanel title="Strategy Parameters" icon={<Wrench className="h-4 w-4" />}>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          {Object.entries(params).map(([k, v]) => (
            <div key={k}>
              <dt className="text-slate-500">{humanize(k)}</dt>
              <dd className="text-white">{String(v)}</dd>
            </div>
          ))}
        </dl>
      </GlassPanel>

      <GlassPanel title="Operator Actions" icon={<Wrench className="h-4 w-4" />}>
        <ul className="text-sm text-slate-300 space-y-1">
          {(data.operator_actions ?? []).map((a) => (
            <li key={a.endpoint}>{a.label}</li>
          ))}
        </ul>
        <button
          type="button"
          disabled={busy}
          onClick={() => void repairBootstrap()}
          className="mt-3 rounded-lg border border-hive-cyan/40 px-3 py-2 text-sm text-hive-cyan hover:bg-hive-cyan/10 disabled:opacity-50"
        >
          Repair database bootstrap
        </button>
        {msg && <p className="text-xs text-slate-400 mt-2">{msg}</p>}
      </GlassPanel>

      <DangerZonePanel embedded />
    </section>
  );
}
