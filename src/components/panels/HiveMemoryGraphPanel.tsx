"use client";

import { useCallback, useEffect, useState } from "react";
import { Network } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { MemoryLessonDrawer, type LessonDetail } from "@/components/panels/MemoryLessonDrawer";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
}

interface Props {
  compact?: boolean;
  showArchived?: boolean;
  categoryFilter?: CategoryFilter;
}

export function HiveMemoryGraphPanel({
  compact = false,
  showArchived = false,
  categoryFilter = "all",
}: Props) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<LessonDetail | null>(null);
  const [filter, setFilter] = useState<CategoryFilter>(categoryFilter);
  const [archived, setArchived] = useState(showArchived);

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
      setNodes(data.nodes || []);
      setEdges(data.edges || []);
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

  async function onNodeClick(node: GraphNode) {
    if (node.type === "hive") return;
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

  const lessonNodes = nodes.filter((n) => n.id !== "hive");
  const filters: { id: CategoryFilter; label: string }[] = [
    { id: "all", label: "All" },
    { id: "trading_memory", label: "Trading" },
    { id: "system_issue", label: "System issues" },
    { id: "ai_review_memory", label: "AI reviews" },
    { id: "operator_note", label: "Operator" },
  ];

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
              className={`text-[9px] px-2 py-0.5 rounded border ${
                filter === f.id
                  ? "border-hive-cyan text-hive-cyan bg-hive-cyan/10"
                  : "border-white/10 text-slate-500"
              }`}
            >
              {f.label}
            </button>
          ))}
          <label className="flex items-center gap-1 text-[9px] text-slate-500 ml-auto">
            <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />
            Archived
          </label>
        </div>
        {loading ? (
          <EmptyState message="Loading memory graph…" className="min-h-[160px]" />
        ) : error ? (
          <EmptyState message={error} className="min-h-[160px]" />
        ) : lessonNodes.length === 0 ? (
          <EmptyState message="No memories in this filter" className="min-h-[160px]" />
        ) : (
          <>
            <figure className={`relative w-full ${compact ? "min-h-[180px]" : "min-h-[220px]"} aspect-[4/3]`}>
              <svg viewBox="0 0 100 100" className="w-full h-full" aria-label="Hive memory network graph">
                <defs>
                  <filter id="memGlow">
                    <feGaussianBlur stdDeviation="0.6" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                </defs>
                {edges.map((e) => {
                  const s = nodes.find((n) => n.id === e.source);
                  const t = nodes.find((n) => n.id === e.target);
                  if (!s || !t) return null;
                  return (
                    <line
                      key={e.id}
                      x1={s.x}
                      y1={s.y}
                      x2={t.x}
                      y2={t.y}
                      stroke="#475569"
                      strokeWidth="0.2"
                      strokeOpacity="0.5"
                    />
                  );
                })}
                <polygon
                  points="50,42 56,46 56,54 50,58 44,54 44,46"
                  fill="#0e7490"
                  fillOpacity="0.35"
                  stroke="#22d3ee"
                  strokeWidth="0.4"
                  filter="url(#memGlow)"
                />
                <text x={50} y={51} textAnchor="middle" fill="#22d3ee" fontSize="3.2" fontWeight="bold">
                  HIVE
                </text>
                {lessonNodes.map((node) => (
                  <g
                    key={node.id}
                    transform={`translate(${node.x}, ${node.y})`}
                    className="cursor-pointer"
                    onClick={() => onNodeClick(node)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(ev) => ev.key === "Enter" && onNodeClick(node)}
                  >
                    <circle
                      r="5"
                      fill={node.color || "#3b82f6"}
                      fillOpacity="0.35"
                      stroke={node.color || "#3b82f6"}
                      strokeWidth="0.5"
                      filter="url(#memGlow)"
                    />
                    <text y="-6" textAnchor="middle" fill="#94a3b8" fontSize="2.2">
                      {node.label}
                    </text>
                    {node.badge && (
                      <text y="8" textAnchor="middle" fill="#fbbf24" fontSize="1.8">
                        {node.badge}
                      </text>
                    )}
                  </g>
                ))}
              </svg>
            </figure>
            <p className="text-[10px] text-slate-500 mt-2 text-center">
              {lessonNodes.length} node(s) — click for drawer
            </p>
          </>
        )}
      </GlassPanel>
      <MemoryLessonDrawer detail={selected} onClose={() => setSelected(null)} onUpdated={load} />
    </>
  );
}
