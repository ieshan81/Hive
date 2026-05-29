"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Lock,
  Settings as SettingsIcon,
  ShieldAlert,
  CheckCircle2,
  PauseCircle,
  PlayCircle,
  ToggleLeft,
  ToggleRight,
  Sparkles,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type SettingsStatus = {
  status: string;
  generated_at_utc?: string;
  system_mode?: {
    environment_mode?: string;
    paper_trading_only?: boolean;
    live_trading_enabled?: boolean;
    live_lock_status?: string;
    broker_base_url?: string;
    broker_mode_detected?: string;
    alpaca_connected?: boolean;
    gemini_configured?: boolean;
    database_configured?: boolean;
  };
  paper_subset?: Record<string, unknown>;
  live_subset_readonly?: { note?: string };
  active_config_version?: number;
};

type Readiness = {
  paper_broker_connected?: boolean;
  alpaca_configured?: boolean;
  paper_orders_enabled?: boolean;
  paper_learning_enabled?: boolean;
  scheduler_enabled?: boolean;
  blockers?: string[];
  blockers_count?: number;
  kill_switch_active?: boolean;
  kill_switch_reason?: string;
  bot_can_trade?: boolean;
  next_action?: string;
  live_trading_unchanged?: boolean;
  submitted_order?: boolean;
};

type DryRunResult = {
  status: string;
  old_config_subset?: Record<string, unknown>;
  new_config_subset?: Record<string, unknown>;
  changed_keys?: string[];
  rejected_paths?: string[];
  safety_checks?: {
    rejected_forbidden_paths?: string[];
    rejected_unknown_paths?: string[];
  };
  live_trading_unchanged?: boolean;
  submitted_order?: boolean;
};

const PAPER_KEY_LABELS: Record<string, string> = {
  "execution.paper_orders_enabled": "Paper orders enabled",
  "execution.max_orders_per_cycle": "Max paper orders per cycle",
  "execution.max_orders_per_hour": "Max paper orders per hour",
  "execution.max_orders_per_day": "Max paper orders per day",
  "execution.min_seconds_between_orders_per_symbol": "Min seconds between orders (per symbol)",
  "execution.quote_max_age_seconds": "Quote max age (seconds)",
  "execution.max_paper_notional_per_trade_usd": "Max paper notional per trade ($)",
  "execution.duplicate_symbol_protection_enabled": "Duplicate position prevention",
  "execution.min_trade_notional_usd": "Min trade notional ($)",
  "autonomous_paper_learning.mode_enabled": "Paper learning enabled",
  "autonomous_paper_learning.scheduler_enabled": "Scheduler enabled",
  "autonomous_paper_learning.scheduler_interval_seconds": "Scheduler interval (seconds)",
  "autonomous_paper_learning.max_paper_trades_per_day": "Max paper trades per day",
  "autonomous_paper_learning.max_paper_notional_per_trade_usd": "Max learning notional per trade ($)",
  "autonomous_paper_learning.default_paper_notional_usd": "Default paper notional ($)",
  "autonomous_paper_learning.max_open_paper_positions": "Max open paper positions",
  "autonomous_paper_learning.max_daily_paper_loss_pct": "Max daily paper loss (%)",
  "autonomous_paper_learning.max_weekly_paper_loss_pct": "Max weekly paper loss (%)",
  "portfolio.max_concurrent_positions": "Max concurrent positions",
  "portfolio.max_total_exposure_pct": "Max total exposure (%)",
  "portfolio.reserve_cash_pct": "Reserve cash (%)",
  "risk.daily_drawdown_pct": "Daily drawdown limit (%)",
  "risk.max_drawdown_pct": "Max drawdown limit (%)",
  "risk.max_exposure_per_symbol_pct": "Max exposure per symbol (%)",
  "min_edge_after_cost_bps": "Min edge after cost (bps)",
};

const PAPER_CONTROL_KEYS = [
  "execution.paper_orders_enabled",
  "autonomous_paper_learning.mode_enabled",
  "autonomous_paper_learning.scheduler_enabled",
  "execution.max_paper_notional_per_trade_usd",
  "execution.max_orders_per_cycle",
  "execution.max_orders_per_hour",
  "execution.max_orders_per_day",
  "execution.min_seconds_between_orders_per_symbol",
  "execution.duplicate_symbol_protection_enabled",
];
const PAPER_RISK_KEYS = [
  "risk.daily_drawdown_pct",
  "risk.max_drawdown_pct",
  "risk.max_exposure_per_symbol_pct",
  "portfolio.reserve_cash_pct",
  "portfolio.max_concurrent_positions",
  "min_edge_after_cost_bps",
  "execution.quote_max_age_seconds",
];

function formatValue(v: unknown): string {
  if (v === true) return "yes";
  if (v === false) return "no";
  if (v === null || v === undefined) return "—";
  return String(v);
}

function labelFor(key: string): string {
  return PAPER_KEY_LABELS[key] ?? key.replace(/_/g, " ");
}

export function PaperSettingsPanel() {
  const [status, setStatus] = useState<SettingsStatus | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [dryRunResult, setDryRunResult] = useState<DryRunResult | null>(null);
  const [confirmInput, setConfirmInput] = useState("");
  const [showTech, setShowTech] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [s, r] = await Promise.all([
      apiGet<SettingsStatus>("/api/settings/status", { timeoutMs: 5000 }),
      apiGet<Readiness>("/api/settings/paper-trading/readiness", { timeoutMs: 5000 }),
    ]);
    if (s.ok && s.data) setStatus(s.data);
    if (r.ok && r.data) setReadiness(r.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function runReadinessCheck() {
    setBusy(true);
    setMsg(null);
    const r = await apiPostOperator<Readiness>("/api/execution/paper/readiness-check", {});
    if (r.ok && r.data) {
      setReadiness(r.data);
      setMsg(
        r.data.bot_can_trade
          ? "Readiness check passed — operator may run a controlled paper cycle from Cockpit."
          : `Readiness check complete — ${r.data.blockers_count ?? 0} blocker(s).`,
      );
    } else {
      setMsg(r.error ?? "Readiness check failed.");
    }
    setBusy(false);
  }

  async function presetDryRun() {
    setBusy(true);
    setMsg(null);
    setDryRunResult(null);
    const r = await apiPostOperator<DryRunResult>("/api/settings/paper-trading/dry-run", {
      preset: "paper_learning_v1",
    });
    if (r.ok && r.data) {
      setDryRunResult(r.data);
      setMsg(`Dry-run: ${r.data.changed_keys?.length ?? 0} field(s) would change. Nothing was written.`);
    } else {
      setMsg(r.error ?? "Dry-run failed.");
    }
    setBusy(false);
  }

  async function presetApply() {
    if (confirmInput.trim().toUpperCase() !== "APPLY PAPER LEARNING PRESET") {
      setMsg('Type "APPLY PAPER LEARNING PRESET" to confirm.');
      return;
    }
    setBusy(true);
    setMsg(null);
    const r = await apiPostOperator<DryRunResult>("/api/settings/paper-trading/apply", {
      preset: "paper_learning_v1",
      confirmation: "APPLY PAPER LEARNING PRESET",
    });
    if (r.ok && r.data) {
      setMsg(
        `Preset applied — ${r.data.changed_keys?.length ?? 0} field(s) updated. Live trading unchanged. No order submitted.`,
      );
      setConfirmInput("");
      setDryRunResult(null);
      await load();
    } else {
      setMsg(r.error ?? "Apply failed.");
    }
    setBusy(false);
  }

  async function quickAction(path: string, label: string) {
    setBusy(true);
    setMsg(null);
    const r = await apiPostOperator<DryRunResult>(`/api/settings/paper-trading/${path}`, {});
    if (r.ok && r.data) {
      setMsg(`${label}: ok (${r.data.changed_keys?.length ?? 0} field(s) changed).`);
      await load();
    } else {
      setMsg(`${label}: ${r.error ?? "failed"}`);
    }
    setBusy(false);
  }

  const mode = status?.system_mode;
  const paperSubset = status?.paper_subset ?? {};
  const blockers = useMemo(() => readiness?.blockers ?? [], [readiness?.blockers]);
  const drawdownBlocker = useMemo(
    () => blockers.find((b) => b.toLowerCase().includes("drawdown")),
    [blockers],
  );

  return (
    <section className="space-y-4">
      {/* 1. System Mode */}
      <article className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
        <h2 className="mb-2 flex items-center gap-2 text-base font-semibold text-white">
          <SettingsIcon className="h-4 w-4 text-hive-cyan" /> System Mode
        </h2>
        <p className="mb-3 text-xs text-slate-400">
          Live trading is locked at the platform level. This page can only modify paper-only configuration.
        </p>
        <div className="grid gap-2 md:grid-cols-3 text-xs">
          <Field label="Environment mode" value={mode?.environment_mode ?? "paper"} />
          <Field label="Paper trading only" value={mode?.paper_trading_only ? "yes" : "no"} />
          <Field label="Live trading enabled" value={mode?.live_trading_enabled ? "yes" : "no"} highlight={mode?.live_trading_enabled ? "danger" : "ok"} />
          <Field label="Live lock" value={mode?.live_lock_status ?? "—"} highlight={mode?.live_lock_status === "locked" ? "ok" : "warn"} />
          <Field label="Broker mode" value={mode?.broker_mode_detected ?? "—"} highlight={mode?.broker_mode_detected === "paper" ? "ok" : "warn"} />
          <Field label="Alpaca connected" value={mode?.alpaca_connected ? "yes" : "no"} highlight={mode?.alpaca_connected ? "ok" : "warn"} />
          <Field label="Gemini configured" value={mode?.gemini_configured ? "yes" : "no"} />
          <Field label="DB configured" value={mode?.database_configured ? "yes" : "no"} />
          <Field label="Active config version" value={status?.active_config_version ?? "—"} />
        </div>
        <div className="mt-3 flex items-center gap-2 rounded border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-300">
          <Lock className="h-3.5 w-3.5" />
          LIVE LOCKED · Live trading cannot be enabled from this page.
        </div>
      </article>

      {/* 4. Paper Trading Readiness (placed early — answers user's main question) */}
      <article className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
        <h2 className="mb-2 flex items-center gap-2 text-base font-semibold text-white">
          <ShieldAlert className="h-4 w-4 text-hive-cyan" /> Paper Trading Readiness
        </h2>
        <p className="mb-3 text-xs text-slate-400">
          Reflects the same truth as Cockpit. Submits no order. Does not run a cycle.
        </p>
        <div className="grid gap-2 md:grid-cols-2 text-xs">
          <Field label="Paper broker connected" value={readiness?.paper_broker_connected ? "yes" : "no"} highlight={readiness?.paper_broker_connected ? "ok" : "warn"} />
          <Field label="Paper orders enabled" value={readiness?.paper_orders_enabled ? "yes" : "no"} />
          <Field label="Paper learning enabled" value={readiness?.paper_learning_enabled ? "yes" : "no"} />
          <Field label="Scheduler enabled" value={readiness?.scheduler_enabled ? "yes" : "no"} />
          <Field label="Kill switch active" value={readiness?.kill_switch_active ? "yes" : "no"} highlight={readiness?.kill_switch_active ? "warn" : "ok"} />
          <Field label="Bot can trade" value={readiness?.bot_can_trade ? "yes" : "no"} highlight={readiness?.bot_can_trade ? "ok" : "warn"} />
        </div>
        {drawdownBlocker ? (
          <div className="mt-3 flex items-start gap-2 rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div>
              <p className="font-medium">Active blocker:</p>
              <p className="font-mono opacity-90">{drawdownBlocker}</p>
            </div>
          </div>
        ) : null}
        {blockers.length > 0 ? (
          <ul className="mt-3 space-y-1 text-[11px] text-slate-400">
            {blockers.map((b) => (
              <li key={b}>
                <span className="text-amber-300">•</span> {b}
              </li>
            ))}
          </ul>
        ) : null}
        {readiness?.next_action ? (
          <p className="mt-2 text-[11px] text-slate-300">
            <span className="text-slate-500">Next action: </span>
            {readiness.next_action}
          </p>
        ) : null}
        <button
          type="button"
          disabled={busy}
          onClick={runReadinessCheck}
          className="mt-3 inline-flex items-center gap-1 rounded-lg border border-hive-cyan/30 bg-hive-cyan/10 px-3 py-1.5 text-xs text-hive-cyan hover:bg-hive-cyan/20 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />
          Check paper-entry readiness
        </button>
      </article>

      {/* 5. Operator Actions / Paper Learning Preset */}
      <article className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
        <h2 className="mb-2 flex items-center gap-2 text-base font-semibold text-white">
          <Sparkles className="h-4 w-4 text-hive-cyan" /> Operator Actions
        </h2>
        <p className="mb-3 text-xs text-slate-400">
          Safe operator-only mutations through ConfigManager. Never touches live flags. Never submits orders.
        </p>

        <div className="flex flex-wrap gap-2 mb-3">
          <button type="button" disabled={busy} onClick={() => quickAction("resume", "Resume paper learning")} className="inline-flex items-center gap-1 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/5 disabled:opacity-50">
            <PlayCircle className="h-3.5 w-3.5" /> Resume paper learning
          </button>
          <button type="button" disabled={busy} onClick={() => quickAction("pause", "Pause paper learning")} className="inline-flex items-center gap-1 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/5 disabled:opacity-50">
            <PauseCircle className="h-3.5 w-3.5" /> Pause paper learning
          </button>
          <button type="button" disabled={busy} onClick={() => quickAction("enable-orders", "Enable paper orders")} className="inline-flex items-center gap-1 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/5 disabled:opacity-50">
            <ToggleRight className="h-3.5 w-3.5" /> Enable paper orders
          </button>
          <button type="button" disabled={busy} onClick={() => quickAction("disable-orders", "Disable paper orders")} className="inline-flex items-center gap-1 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/5 disabled:opacity-50">
            <ToggleLeft className="h-3.5 w-3.5" /> Disable paper orders
          </button>
          <button type="button" disabled={busy} onClick={load} className="inline-flex items-center gap-1 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/5 disabled:opacity-50">
            <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>

        <div className="rounded border border-white/10 bg-black/30 p-3">
          <p className="text-xs font-medium text-white mb-1">Paper Learning Preset</p>
          <p className="text-[11px] text-slate-400 mb-2">
            Conservative preset for a $200 paper account. Daily drawdown limit is unchanged unless you opt in separately.
          </p>
          <div className="flex flex-wrap gap-2 mb-2">
            <button type="button" disabled={busy} onClick={presetDryRun} className="inline-flex items-center gap-1 rounded-lg border border-hive-cyan/30 bg-hive-cyan/10 px-3 py-1.5 text-xs text-hive-cyan hover:bg-hive-cyan/20 disabled:opacity-50">
              <Sparkles className="h-3.5 w-3.5" /> Dry-run preset
            </button>
            <input
              type="text"
              value={confirmInput}
              onChange={(e) => setConfirmInput(e.target.value)}
              placeholder="Type: APPLY PAPER LEARNING PRESET"
              className="flex-1 min-w-[240px] rounded border border-white/10 bg-black/40 px-2 py-1.5 text-xs text-white placeholder-slate-500 font-mono"
            />
            <button
              type="button"
              disabled={busy || confirmInput.trim().toUpperCase() !== "APPLY PAPER LEARNING PRESET"}
              onClick={presetApply}
              className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-40"
            >
              <CheckCircle2 className="h-3.5 w-3.5" /> Apply preset
            </button>
          </div>

          {dryRunResult ? (
            <div className="mt-2 rounded border border-white/10 bg-black/40 p-2">
              <p className="text-[11px] font-medium text-slate-300 mb-1">
                Dry-run preview · {dryRunResult.changed_keys?.length ?? 0} field(s) would change
              </p>
              <p className="text-[10px] text-slate-500 mb-2">
                live_trading_unchanged: {dryRunResult.live_trading_unchanged ? "yes" : "no"} · submitted_order: {dryRunResult.submitted_order ? "yes" : "no"}
              </p>
              <div className="max-h-40 overflow-auto space-y-0.5 text-[10px] font-mono">
                {Object.entries(dryRunResult.new_config_subset ?? {}).map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[1fr_auto_auto] gap-2 text-slate-400 border-b border-white/5 py-0.5">
                    <span className="truncate" title={k}>{k}</span>
                    <span className="text-slate-600 line-through">{formatValue(dryRunResult.old_config_subset?.[k])}</span>
                    <span className="text-hive-cyan">→ {formatValue(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        {msg ? <p className="mt-3 text-[11px] text-slate-300">{msg}</p> : null}
      </article>

      {/* 2. Paper Trading Controls */}
      <article className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
        <h2 className="mb-2 flex items-center gap-2 text-base font-semibold text-white">
          <SettingsIcon className="h-4 w-4 text-hive-cyan" /> Paper Trading Controls
        </h2>
        <p className="mb-3 text-xs text-slate-400">
          Read-only summary of paper-execution settings. Use Operator Actions above to change them.
        </p>
        <div className="grid gap-1.5 md:grid-cols-2 text-[11px]">
          {PAPER_CONTROL_KEYS.map((k) => (
            <Field key={k} label={labelFor(k)} value={formatValue(paperSubset[k])} />
          ))}
        </div>
      </article>

      {/* 3. Paper Risk Controls */}
      <article className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
        <h2 className="mb-2 flex items-center gap-2 text-base font-semibold text-white">
          <ShieldAlert className="h-4 w-4 text-hive-cyan" /> Paper Risk Controls
        </h2>
        <p className="mb-3 text-xs text-slate-400">
          The daily drawdown limit is the most common blocker. Change it only with intent.
        </p>
        <div className="grid gap-1.5 md:grid-cols-2 text-[11px]">
          {PAPER_RISK_KEYS.map((k) => (
            <Field
              key={k}
              label={labelFor(k)}
              value={formatValue(paperSubset[k])}
              highlight={k === "risk.daily_drawdown_pct" ? "warn" : undefined}
            />
          ))}
        </div>
      </article>

      {/* 6. Technical Config Drawer */}
      <article className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
        <button
          type="button"
          onClick={() => setShowTech((v) => !v)}
          className="text-[11px] text-slate-400 underline"
        >
          {showTech ? "Hide" : "Show"} technical details
        </button>
        {showTech ? (
          <pre className="mt-2 max-h-60 overflow-auto rounded bg-black/40 p-2 text-[10px] text-slate-500">
            {JSON.stringify({ status, readiness }, null, 2)}
          </pre>
        ) : null}
      </article>

      {loading ? <p className="text-[11px] text-slate-500">Loading settings…</p> : null}
    </section>
  );
}

function Field({
  label,
  value,
  highlight,
}: {
  label: string;
  value: unknown;
  highlight?: "ok" | "warn" | "danger";
}) {
  const color =
    highlight === "ok"
      ? "text-emerald-300"
      : highlight === "warn"
      ? "text-amber-300"
      : highlight === "danger"
      ? "text-red-300"
      : "text-white";
  return (
    <div className="rounded border border-white/10 bg-black/20 px-2.5 py-1.5">
      <p className="text-slate-500 text-[10px]">{label}</p>
      <p className={`font-medium font-mono ${color}`}>{String(value ?? "—")}</p>
    </div>
  );
}
