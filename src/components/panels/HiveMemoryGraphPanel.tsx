"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { Network } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { PanelError } from "@/components/ui/PanelError";
import { MemoryLessonDrawer, type LessonDetail } from "@/components/panels/MemoryLessonDrawer";
import { apiGet } from "@/lib/apiClient";
import { isLessonGraphNode, lessonNodeIdForApi, normalizeMemoryGraph } from "@/lib/apiNormalize";
import type { MemoryGraphNode } from "@/types/api";
import type { PanelLoadMeta } from "@/types/api";

const CX = 50;
const CY = 50;

type CategoryFilter =
  | "all"
  | "trading_memory"
  | "research_memory"
  | "strategy_research_memory"
  | "backtest_memory"
  | "symbol_pattern"
  | "system_issue"
  | "ai_review_memory"
  | "operator_note";

interface Props {
  compact?: boolean;
  showArchived?: boolean;
  categoryFilter?: CategoryFilter;
}

function layoutLessonNodes(lessons: MemoryGraphNode[]): (MemoryGraphNode & { angle: number })[] {
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

function labelPosition(node: MemoryGraphNode & { angle: number }) {
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
  const [rawNodes, setRawNodes] = useState<MemoryGraphNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [meta, setMeta] = useState<PanelLoadMeta>({ source: "empty", lastUpdated: new Date().toISOString() });
  const [selected, setSelected] = useState<LessonDetail | null>(null);
  const [filter, setFilter] = useState<CategoryFilter>(categoryFilter);
  const [archived, setArchived] = useState(showArchived);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [graphMeta, setGraphMeta] = useState<Record<string, unknown> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (filter !== "all") params.set("category", filter);
    if (archived) {
      params.set("include_archived", "true");
      params.set("graph_default", "false");
    } else {
      params.set("graph_default", filter === "all" ? "true" : "false");
    }
    const path = `/api/memory/graph?${params}`;
    const result = await apiGet<unknown>(path);
    if (result.ok && result.data) {
      const graph = normalizeMemoryGraph(result.data);
      setRawNodes(graph.nodes);
      const gm = (result.data as Record<string, unknown>).meta;
      setGraphMeta(gm && typeof gm === "object" ? (gm as Record<string, unknown>) : null);
      setMeta({
        source: "live_api",
        lastUpdated: new Date().toISOString(),
        endpoint: path,
        httpStatus: result.status,
      });
    } else {
      setRawNodes([]);
      setGraphMeta(null);
      setMeta({
        source: "empty",
        lastUpdated: new Date().toISOString(),
        endpoint: path,
        httpStatus: result.status,
        error: result.error || `HTTP ${result.status}`,
      });
    }
    setLoading(false);
  }, [filter, archived]);

  useEffect(() => {
    load();
  }, [load]);

  const lessonNodes = useMemo(
    () => rawNodes.filter((n) => n.type === "lesson" || n.id.startsWith("lesson-")),
    [rawNodes]
  );
  const positioned = useMemo(() => layoutLessonNodes(lessonNodes), [lessonNodes]);

  async function onNodeClick(node: MemoryGraphNode) {
    if (!isLessonGraphNode(node.id, node.type)) return;
    const apiId = lessonNodeIdForApi(node.id);
    const result = await apiGet<{ status?: string; node?: LessonDetail }>(`/api/memory/node/${encodeURIComponent(apiId)}`);
    if (result.ok && result.data) {
      const payload = result.data as { node?: LessonDetail };
      if (payload.node) {
        setSelected(payload.node);
        return;
      }
      if ((result.data as LessonDetail).title) {
        setSelected(result.data as LessonDetail);
      }
    }
  }

  const filters: { id: CategoryFilter; label: string }[] = [
    { id: "all", label: "All" },
    { id: "trading_memory", label: "Trading" },
    { id: "research_memory", label: "Research" },
    { id: "backtest_memory", label: "Backtests" },
    { id: "symbol_pattern", label: "Patterns" },
    { id: "system_issue", label: "System" },
    { id: "ai_review_memory", label: "AI" },
    { id: "operator_note", label: "Operator" },
  ];

  const showError = !loading && meta.error;
  const showEmpty = !loading && !meta.error && positioned.length === 0;
  const emptyReason = graphMeta?.empty_reason as string | undefined;

  return (
    <>
      <GlassPanel
        title={compact ? "Memory graph" : "Hive Memory Graph"}
        icon={<Network className="h-4 w-4" />}
        action={
          <span className="text-[9px] text-slate-600">
            {meta.source === "live_api" ? "live" : meta.source}
          </span>
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
                  : "border-white/10 text-slate-500"
              }`}
            >
              {f.label}
            </button>
          ))}
          <button type="button" onClick={load} className="text-[9px] text-hive-cyan ml-auto">
            Refresh
          </button>
          <label className="flex items-center gap-1 text-[9px] text-slate-500 cursor-pointer">
            <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />
            Archived
          </label>
        </div>

        {loading ? (
          <EmptyState message="Loading memory graph…" className="min-h-[200px]" />
        ) : showError ? (
          <PanelError
            title="Could not load memory graph"
            meta={meta}
            expectedShape='{ status?: "ok", nodes: [...], edges: [...] }'
          />
        ) : showEmpty ? (
          <div className="min-h-[200px] flex flex-col items-center justify-center text-center px-4">
            <EmptyState
              message={emptyReason || "No active memories in this filter."}
              className="min-h-0"
            />
            {graphMeta && (
              <p className="text-[10px] text-slate-500 mt-2">
                Trading: {String(graphMeta.active_trading_memories ?? 0)} · Research:{" "}
                {String(graphMeta.active_research_memories ?? 0)} · Hidden archived/deleted:{" "}
                {String(graphMeta.archived_or_deleted ?? 0)}
              </p>
            )}
          </div>
        ) : (
          <>
            <figure
              className={`relative w-full overflow-hidden rounded-xl border border-white/5 bg-[#030508]/80 ${
                compact ? "min-h-[240px]" : "min-h-[280px]"
              }`}
            >
              <svg viewBox="0 0 100 100" className="w-full h-full" aria-label="Hive memory graph">
                <defs>
                  <filter id={`hiveGlow-${uid}`}>
                    <feGaussianBlur stdDeviation="1.2" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                </defs>
                {positioned.map((node, i) => {
                  const color = node.color || "#3b82f6";
                  const active = hoverId === node.id;
                  const dur = `${2 + (i % 5) * 0.35}s`;
                  const delay = `${i * 0.45}s`;
                  return (
                    <g key={`feed-${node.id}`}>
                      <line x1={node.x} y1={node.y} x2={CX} y2={CY} stroke={color} strokeWidth="0.2" strokeOpacity="0.15" />
                      <line
                        x1={node.x}
                        y1={node.y}
                        x2={CX}
                        y2={CY}
                        stroke={color}
                        strokeWidth="0.4"
                        strokeDasharray="1.5 3"
                        className="hive-feed-dash"
                        style={{ animationDuration: dur, animationDelay: delay }}
                      />
                      <circle r="0.65" fill={color}>
                        <animateMotion dur={dur} begin={delay} repeatCount="indefinite" path={`M ${node.x} ${node.y} L ${CX} ${CY}`} />
                      </circle>
                    </g>
                  );
                })}
                <g filter={`url(#hiveGlow-${uid})`}>
                  <circle cx={CX} cy={CY} r="9" fill="#0e7490" fillOpacity="0.35" className="hive-core-breathe" />
                  <polygon
                    points={`${CX},${CY - 5.5} ${CX + 4.8},${CY - 2.75} ${CX + 4.8},${CY + 2.75} ${CX},${CY + 5.5} ${CX - 4.8},${CY + 2.75} ${CX - 4.8},${CY - 2.75}`}
                    fill="#0c4a6e"
                    stroke="#22d3ee"
                    strokeWidth="0.35"
                  />
                  <text x={CX} y={CY + 1.2} textAnchor="middle" fill="#e0f2fe" fontSize="2.8" fontWeight="700">
                    HIVE
                  </text>
                  <text x={CX} y={CY + 5.5} textAnchor="middle" fill="#67e8f9" fontSize="1.6">
                    {positioned.length}
                  </text>
                </g>
                {positioned.map((node) => {
                  const color = node.color || "#3b82f6";
                  const active = hoverId === node.id;
                  const lbl = labelPosition(node);
                  const short = node.label.length > 22 ? `${node.label.slice(0, 20)}…` : node.label;
                  return (
                    <g
                      key={node.id}
                      className="cursor-pointer"
                      onClick={() => onNodeClick(node)}
                      onMouseEnter={() => setHoverId(node.id)}
                      onMouseLeave={() => setHoverId(null)}
                      role="button"
                      tabIndex={0}
                    >
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r={active ? 5.5 : 4.5}
                        fill={color}
                        fillOpacity={active ? 0.45 : 0.28}
                        stroke={color}
                        strokeWidth="0.4"
                      />
                      <text x={lbl.x} y={lbl.y} textAnchor={lbl.anchor} fill="#94a3b8" fontSize="2.15">
                        <title>{node.label}</title>
                        {short}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </figure>
            <p className="text-[10px] text-slate-500 mt-2 text-center">
              {positioned.length} memories · {meta.source} · click node for evidence
            </p>
          </>
        )}
      </GlassPanel>
      <MemoryLessonDrawer detail={selected} onClose={() => setSelected(null)} onUpdated={load} />
    </>
  );
}
