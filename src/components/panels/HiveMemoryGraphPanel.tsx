"use client";

import { useCallback, useEffect, useState } from "react";
import { Network } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { MemoryLessonDrawer, type LessonDetail } from "@/components/panels/MemoryLessonDrawer";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface GraphNode {
  id: string;
  label: string;
  type: string;
  severity?: string;
  confidence?: number;
  status?: string;
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

export function HiveMemoryGraphPanel() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<LessonDetail | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/memory/graph`);
      const data = await res.json();
      setNodes(data.nodes || []);
      setEdges(data.edges || []);
      setError(null);
    } catch {
      setError("Could not load memory graph");
    } finally {
      setLoading(false);
    }
  }, []);

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
      } else if (node.type === "lesson") {
        setSelected({
          node_id: node.id,
          title: node.label,
          summary: "Open lesson from graph",
          detailed_lesson: "",
          severity: node.severity || "MEDIUM",
          confidence: node.confidence || 0.5,
          source: "graph",
          action_status: node.status || "none",
        });
      }
    } catch {
      setError("Failed to load lesson detail");
    }
  }

  const lessonNodes = nodes.filter((n) => n.id !== "hive");
  const centerX = 50;
  const centerY = 50;

  return (
    <>
      <GlassPanel
        title="Hive Memory Graph"
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
        {loading ? (
          <EmptyState message="Loading memory graph…" className="min-h-[200px]" />
        ) : error ? (
          <EmptyState message={error} className="min-h-[200px]" />
        ) : lessonNodes.length === 0 ? (
          <EmptyState message="No lessons yet — run a cycle or backfill memories" className="min-h-[200px]" />
        ) : (
          <>
            <figure className="relative aspect-[4/3] w-full min-h-[220px]">
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
                  className="cursor-default"
                />
                <text x={centerX} y={centerY + 1} textAnchor="middle" fill="#22d3ee" fontSize="3.2" fontWeight="bold">
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
                      fillOpacity="0.3"
                      stroke={node.color || "#3b82f6"}
                      strokeWidth="0.5"
                      filter="url(#memGlow)"
                    />
                    <text y="-6" textAnchor="middle" fill="#94a3b8" fontSize="2.4">
                      {node.label}
                    </text>
                    {(node.count ?? 1) > 1 && (
                      <text y="8" textAnchor="middle" fill="#fbbf24" fontSize="2.2">
                        ×{node.count}
                      </text>
                    )}
                  </g>
                ))}
              </svg>
            </figure>
            <p className="text-[10px] text-slate-500 mt-2 text-center">
              {lessonNodes.length} lesson node(s) — click to open evidence drawer
            </p>
          </>
        )}
      </GlassPanel>
      <MemoryLessonDrawer detail={selected} onClose={() => setSelected(null)} onUpdated={load} />
    </>
  );
}
