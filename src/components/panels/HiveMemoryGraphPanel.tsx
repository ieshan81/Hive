"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { Network } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { MemoryLessonDrawer, type LessonDetail } from "@/components/panels/MemoryLessonDrawer";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const CX = 50;
const CY = 50;

type CategoryFilter =
  | "all"
  | "trading_memory"
  | "system_issue"
  | "ai_review_memory"
  | "operator_note";

interface GraphNode {
  id: string;
  label: string;
  type: string;
  category?: string;
  severity?: string;
  confidence?: number;
  status?: string;
  badge?: string;
  count?: number;
  color?: string;
  x: number;
  y: number;
  symbol?: string;
}

interface Props {
  compact?: boolean;
  showArchived?: boolean;
  categoryFilter?: CategoryFilter;
}

/** Even radial layout — lesson nodes only (no symbol satellites). */
function layoutLessonNodes(lessons: GraphNode[]): (GraphNode & { angle: number })[] {
  const n = lessons.length;
  if (n === 0) return [];
  const radius = Math.min(40, 30 + n * 1.8);
  const start = -Math.PI / 2;
  return lessons.map((node, i) => {
    const angle = start + (2 * Math.PI * i) / n;
    return {
      ...node,
      angle,
      x: CX + radius * Math.cos(angle),
      y: CY + radius * Math.sin(angle),
    };
  });
}

function labelAnchor(angle: number): "start" | "middle" | "end" {
  const c = Math.cos(angle);
  if (c > 0.35) return "start";
  if (c < -0.35) return "end";
  return "middle";
}

function labelPosition(node: GraphNode & { angle: number }) {
  const pad = 7.5;
  return {
    x: CX + (pad + 33) * Math.cos(node.angle),
    y: CY + (pad + 33) * Math.sin(node.angle),
    anchor: labelAnchor(node.angle),
  };
}

export function HiveMemoryGraphPanel({
  compact = false,
  showArchived = false,
  categoryFilter = "all",
}: Props) {
  const uid = useId().replace(/:/g, "");
  const [rawNodes, setRawNodes] = useState<GraphNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<LessonDetail | null>(null);
  const [filter, setFilter] = useState<CategoryFilter>(categoryFilter);
  const [archived, setArchived] = useState(showArchived);
  const [hoverId, setHoverId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter !== "all") params.set("category", filter);
      if (archived) {
        params.set("include_archived", "true");
        params.set("graph_default", "false");
      } else {
        params.set("graph_default", filter === "all" ? "true" : "false");
      }
      const res = await fetch(`${API_BASE}/api/memory/graph?${params}`);
      const data = await res.json();
      setRawNodes(data.nodes || []);
      setError(null);
    } catch {
      setError("Could not load memory graph");
    } finally {
      setLoading(false);
    }
  }, [filter, archived]);

  useEffect(() => {
    load();
  }, [load]);

  const lessonNodes = useMemo(
    () => rawNodes.filter((n) => n.type === "lesson"),
    [rawNodes]
  );

  const positioned = useMemo(() => layoutLessonNodes(lessonNodes), [lessonNodes]);

  async function onNodeClick(node: GraphNode) {
    try {
      const res = await fetch(`${API_BASE}/api/memory/node/${encodeURIComponent(node.id)}`);
      const data = await res.json();
      if (data.status === "ok" && data.node) {
        setSelected(data.node);
      }
    } catch {
      setError("Failed to load lesson detail");
    }
  }

  const filters: { id: CategoryFilter; label: string }[] = [
    { id: "all", label: "All" },
    { id: "trading_memory", label: "Trading" },
    { id: "system_issue", label: "System" },
    { id: "ai_review_memory", label: "AI" },
    { id: "operator_note", label: "Operator" },
  ];

  const hiveCount = lessonNodes.length;

  return (
    <>
      <GlassPanel
        title={compact ? "Memory graph" : "Hive Memory Graph"}
        icon={<Network className="h-4 w-4" />}
        action={
          <button
            type="button"
            onClick={load}
            className="text-[10px] font-medium text-hive-cyan hover:text-hive-cyan/80 transition"
          >
            Refresh
          </button>
        }
        className="h-full"
      >
        <div className="flex flex-wrap gap-1 mb-2">
          {filters.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              className={`text-[9px] px-2 py-0.5 rounded-full border transition ${
                filter === f.id
                  ? "border-hive-cyan text-hive-cyan bg-hive-cyan/10"
                  : "border-white/10 text-slate-500 hover:border-white/20"
              }`}
            >
              {f.label}
            </button>
          ))}
          <label className="flex items-center gap-1 text-[9px] text-slate-500 ml-auto cursor-pointer">
            <input
              type="checkbox"
              checked={archived}
              onChange={(e) => setArchived(e.target.checked)}
              className="accent-hive-cyan"
            />
            Archived
          </label>
        </div>

        {loading ? (
          <EmptyState message="Loading memory graph…" className="min-h-[200px]" />
        ) : error ? (
          <EmptyState message={error} className="min-h-[200px]" />
        ) : positioned.length === 0 ? (
          <EmptyState message="No memories in this filter" className="min-h-[200px]" />
        ) : (
          <>
            <figure
              className={`relative w-full overflow-hidden rounded-xl border border-white/5 bg-[#030508]/80 ${
                compact ? "min-h-[240px]" : "min-h-[280px]"
              }`}
            >
              <svg
                viewBox="0 0 100 100"
                className="w-full h-full"
                aria-label="Hive memory network — memories feeding the hive"
                preserveAspectRatio="xMidYMid meet"
              >
                <defs>
                  <filter id={`hiveGlow-${uid}`} x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="1.2" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                  <radialGradient id={`hiveCore-${uid}`} cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.45" />
                    <stop offset="100%" stopColor="#0e7490" stopOpacity="0.05" />
                  </radialGradient>
                  <linearGradient id={`feedGrad-${uid}`} x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#22d3ee" stopOpacity="0" />
                    <stop offset="50%" stopColor="#22d3ee" stopOpacity="0.9" />
                    <stop offset="100%" stopColor="#a855f7" stopOpacity="0" />
                  </linearGradient>
                </defs>

                {/* Ambient grid */}
                <circle cx={CX} cy={CY} r="42" fill="none" stroke="#1e293b" strokeWidth="0.15" strokeDasharray="1 2" />
                <circle cx={CX} cy={CY} r="28" fill="none" stroke="#1e293b" strokeWidth="0.1" strokeDasharray="0.8 1.5" />

                {/* Memory feed channels + pulses */}
                {positioned.map((node, i) => {
                  const color = node.color || "#3b82f6";
                  const active = hoverId === node.id;
                  const dur = `${2 + (i % 5) * 0.35}s`;
                  const delay = `${i * 0.45}s`;
                  return (
                    <g key={`feed-${node.id}`}>
                      <line
                        x1={node.x}
                        y1={node.y}
                        x2={CX}
                        y2={CY}
                        stroke={color}
                        strokeWidth={active ? 0.35 : 0.2}
                        strokeOpacity={active ? 0.35 : 0.12}
                      />
                      <line
                        x1={node.x}
                        y1={node.y}
                        x2={CX}
                        y2={CY}
                        stroke={color}
                        strokeWidth="0.4"
                        strokeOpacity="0.55"
                        strokeDasharray="1.5 3"
                        className="hive-feed-dash"
                        style={{ animationDuration: dur, animationDelay: delay }}
                      />
                      <circle r="0.65" fill={color} opacity="0.95" filter={`url(#hiveGlow-${uid})`}>
                        <animateMotion
                          dur={dur}
                          begin={delay}
                          repeatCount="indefinite"
                          path={`M ${node.x} ${node.y} L ${CX} ${CY}`}
                        />
                        <animate attributeName="opacity" values="0.3;1;0.3" dur={dur} repeatCount="indefinite" />
                      </circle>
                    </g>
                  );
                })}

                {/* Central hive */}
                <g filter={`url(#hiveGlow-${uid})`}>
                  <circle cx={CX} cy={CY} r="9" fill={`url(#hiveCore-${uid})`} className="hive-core-breathe" />
                  <circle cx={CX} cy={CY} r="7.5" fill="none" stroke="#22d3ee" strokeWidth="0.25" strokeOpacity="0.5">
                    <animate attributeName="r" values="7.5;11;7.5" dur="3s" repeatCount="indefinite" />
                    <animate
                      attributeName="stroke-opacity"
                      values="0.5;0;0.5"
                      dur="3s"
                      repeatCount="indefinite"
                    />
                  </circle>
                  <polygon
                    points={`${CX},${CY - 5.5} ${CX + 4.8},${CY - 2.75} ${CX + 4.8},${CY + 2.75} ${CX},${CY + 5.5} ${CX - 4.8},${CY + 2.75} ${CX - 4.8},${CY - 2.75}`}
                    fill="#0c4a6e"
                    fillOpacity="0.6"
                    stroke="#22d3ee"
                    strokeWidth="0.35"
                  />
                  <text
                    x={CX}
                    y={CY + 1.2}
                    textAnchor="middle"
                    fill="#e0f2fe"
                    fontSize="2.8"
                    fontWeight="700"
                    style={{ letterSpacing: "0.08em" }}
                  >
                    HIVE
                  </text>
                  <text x={CX} y={CY + 5.5} textAnchor="middle" fill="#67e8f9" fontSize="1.6" opacity="0.85">
                    {hiveCount}
                  </text>
                </g>

                {/* Lesson nodes */}
                {positioned.map((node) => {
                  const color = node.color || "#3b82f6";
                  const active = hoverId === node.id;
                  const lbl = labelPosition(node);
                  const short =
                    node.label.length > 22 ? `${node.label.slice(0, 20)}…` : node.label;
                  return (
                    <g
                      key={node.id}
                      className="cursor-pointer"
                      onClick={() => onNodeClick(node)}
                      onMouseEnter={() => setHoverId(node.id)}
                      onMouseLeave={() => setHoverId(null)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(ev) => ev.key === "Enter" && onNodeClick(node)}
                    >
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r={active ? 5.5 : 4.5}
                        fill={color}
                        fillOpacity={active ? 0.45 : 0.28}
                        stroke={color}
                        strokeWidth={active ? 0.6 : 0.4}
                        filter={`url(#hiveGlow-${uid})`}
                      />
                      {(node.count ?? 1) > 1 && (
                        <text x={node.x} y={node.y + 1.2} textAnchor="middle" fill="#fef3c7" fontSize="2" fontWeight="bold">
                          {node.count}
                        </text>
                      )}
                      <text
                        x={lbl.x}
                        y={lbl.y}
                        textAnchor={lbl.anchor}
                        fill={active ? "#e2e8f0" : "#94a3b8"}
                        fontSize="2.15"
                        fontWeight={active ? "600" : "400"}
                      >
                        <title>{node.label}</title>
                        {short}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </figure>

            <footer className="flex flex-wrap items-center justify-center gap-4 mt-2 text-[9px] text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-6 h-px bg-gradient-to-r from-cyan-500/80 to-transparent" />
                Memory feed
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-2 h-2 rounded-full bg-cyan-400/80 animate-pulse" />
                Pulse → HIVE
              </span>
              <span>
                <span className="text-cyan-400">●</span> Trading
                <span className="mx-1.5 text-orange-400">●</span> System
              </span>
            </footer>
            <p className="text-[10px] text-slate-600 mt-1 text-center">
              {positioned.length} memories feeding the hive — click a node for evidence
            </p>
          </>
        )}
      </GlassPanel>
      <MemoryLessonDrawer detail={selected} onClose={() => setSelected(null)} onUpdated={load} />
    </>
  );
}
