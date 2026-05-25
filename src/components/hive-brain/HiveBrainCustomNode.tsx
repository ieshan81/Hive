"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

export type HiveBrainNodeData = {
  label: string;
  fullLabel?: string;
  nodeType: string;
  shape?: string;
  color?: string;
  statusRing?: string;
  severity?: string;
  count?: number;
  source?: string;
  trueHoldMinutes?: number | null;
};

function ringClass(ring?: string) {
  if (ring === "red") return "ring-2 ring-red-500/80";
  if (ring === "green") return "ring-2 ring-emerald-500/60";
  return "ring-1 ring-white/15";
}

function shapeBody(shape: string | undefined, color: string, nodeType: string) {
  const base = { borderColor: color, backgroundColor: `${color}22` };
  if (nodeType === "hive" || shape === "brain_core") {
    return (
      <div
        className="w-14 h-14 flex items-center justify-center rounded-lg border-2 font-bold text-[9px] text-cyan-100"
        style={base}
      >
        HIVE
      </div>
    );
  }
  if (nodeType === "cluster" || shape === "cluster_hub") {
    return (
      <div
        className="min-w-[72px] px-2 py-1.5 rounded-full border text-[9px] font-semibold text-violet-100 text-center"
        style={base}
      >
        {nodeType === "cluster" ? "◆ " : ""}
      </div>
    );
  }
  if (nodeType === "position" || shape === "portfolio_card") {
    return (
      <div className="min-w-[80px] px-2 py-2 rounded-md border-2 text-[9px] font-semibold text-cyan-50" style={base}>
        📊
      </div>
    );
  }
  if (nodeType === "strategy" || shape === "diamond") {
    return (
      <div
        className="w-10 h-10 rotate-45 border-2 flex items-center justify-center"
        style={{ ...base, transform: "rotate(45deg)" }}
      />
    );
  }
  return (
    <div className="w-8 h-8 rounded-full border-2" style={base} />
  );
}

export function HiveBrainCustomNode({ data, selected }: NodeProps) {
  const d = data as HiveBrainNodeData;
  const color = d.color || "#22d3ee";
  return (
    <div className={`relative ${ringClass(d.statusRing)} ${selected ? "scale-105" : ""} transition-transform`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-600 !w-1.5 !h-1.5" />
      {shapeBody(d.shape, color, d.nodeType)}
      <p className="mt-1 max-w-[100px] text-[8px] text-slate-300 text-center leading-tight truncate" title={d.fullLabel || d.label}>
        {d.label}
      </p>
      {d.nodeType === "position" && d.trueHoldMinutes != null && (
        <p className="text-[7px] text-cyan-400/90 text-center">{d.trueHoldMinutes.toFixed(0)}m hold</p>
      )}
      {d.count != null && d.count > 0 && d.nodeType === "cluster" && (
        <span className="absolute -top-1 -right-1 text-[7px] bg-violet-600 text-white rounded-full px-1">{d.count}</span>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-slate-600 !w-1.5 !h-1.5" />
    </div>
  );
}
