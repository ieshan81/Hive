"use client";

import { Network } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import type { MemoryGraphData } from "@/types/dashboard";

interface HiveMemoryGraphPanelProps {
  memoryGraph: MemoryGraphData;
}

export function HiveMemoryGraphPanel({ memoryGraph }: HiveMemoryGraphPanelProps) {
  const { nodes, status, message } = memoryGraph;
  const centerX = 50;
  const centerY = 50;

  return (
    <GlassPanel
      title="Hive Memory Graph"
      icon={<Network className="h-4 w-4" />}
      action={
        <button type="button" className="text-[10px] font-medium text-hive-cyan hover:text-hive-cyan/80 transition">
          View Full Graph
        </button>
      }
      className="h-full"
    >
      {status === "empty" || nodes.length === 0 ? (
        <EmptyState message={message ?? "Memory empty"} className="min-h-[200px]" />
      ) : (
        <>
          <figure className="relative aspect-[4/3] w-full min-h-[200px]">
            <svg viewBox="0 0 100 100" className="w-full h-full" aria-label="Hive memory network graph">
              <defs>
                <filter id="glow">
                  <feGaussianBlur stdDeviation="0.8" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
                <radialGradient id="hiveCore" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="#00d1ff" stopOpacity="0.4" />
                  <stop offset="100%" stopColor="#8a2be2" stopOpacity="0.1" />
                </radialGradient>
              </defs>
              {nodes.map((node) => (
                <g key={`edge-${node.id}`}>
                  <line x1={centerX} y1={centerY} x2={node.x} y2={node.y} stroke={node.color} strokeWidth="0.3" strokeOpacity="0.35" filter="url(#glow)" />
                  <line x1={centerX} y1={centerY} x2={node.x} y2={node.y} stroke={node.color} strokeWidth="0.15" strokeOpacity="0.6" strokeDasharray="1 1" />
                </g>
              ))}
              <polygon points="50,42 56,46 56,54 50,58 44,54 44,46" fill="url(#hiveCore)" stroke="#00d1ff" strokeWidth="0.5" filter="url(#glow)" />
              <text x={centerX} y={centerY + 1} textAnchor="middle" fill="#00d1ff" fontSize="3.5" fontWeight="bold">HIVE</text>
              {nodes.map((node) => (
                <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
                  <circle r="4" fill={node.color} fillOpacity="0.25" stroke={node.color} strokeWidth="0.4" filter="url(#glow)" />
                  <circle r="1.5" fill={node.color} />
                  <text y="-5.5" textAnchor="middle" fill="#94a3b8" fontSize="2.8" fontWeight="500">{node.label}</text>
                  <text y="7.5" textAnchor="middle" fill="#e2e8f0" fontSize="3" fontWeight="bold">{node.count.toLocaleString()}</text>
                </g>
              ))}
            </svg>
          </figure>
          <footer className="flex items-center justify-center gap-6 mt-2 pt-2 border-t border-white/5">
            <span className="flex items-center gap-2 text-[9px] text-slate-500">
              <span className="inline-block w-4 h-px bg-slate-400" /> Cause / Effect
            </span>
            <span className="flex items-center gap-2 text-[9px] text-slate-500">
              <span className="inline-block w-4 h-px border-t border-dashed border-slate-400" /> Influence
            </span>
          </footer>
        </>
      )}
    </GlassPanel>
  );
}
