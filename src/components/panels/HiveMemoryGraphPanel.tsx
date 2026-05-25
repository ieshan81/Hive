"use client";

import { useCallback, useEffect, useState } from "react";
import { Network } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { PanelError } from "@/components/ui/PanelError";
import { MemoryLessonDrawer, type LessonDetail } from "@/components/panels/MemoryLessonDrawer";
import { HiveBrainCanvas } from "@/components/hive-brain/HiveBrainCanvas";
import { HiveBrainDrawer } from "@/components/hive-brain/HiveBrainDrawer";
import { apiGet, apiPost } from "@/lib/apiClient";
import { lessonNodeIdForApi } from "@/lib/apiNormalize";
import type { PanelLoadMeta } from "@/types/api";
import type {
  HiveBrainGraphResponse,
  HiveBrainNodeDrawer,
  HiveBrainNodeResponse,
} from "@/types/hiveBrain";

interface Props {
  compact?: boolean;
  showArchived?: boolean;
  categoryFilter?: string;
}

export function HiveMemoryGraphPanel({ compact = false }: Props) {
  const [graph, setGraph] = useState<HiveBrainGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [meta, setMeta] = useState<PanelLoadMeta>({ source: "empty", lastUpdated: new Date().toISOString() });
  const [showRaw, setShowRaw] = useState(false);
  const [expandCluster, setExpandCluster] = useState<string | null>(null);
  const [brainBusy, setBrainBusy] = useState(false);
  const [drawerNode, setDrawerNode] = useState<HiveBrainNodeDrawer | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [legacyLesson, setLegacyLesson] = useState<LessonDetail | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (showRaw) params.set("show_raw", "true");
    if (expandCluster) params.set("expand_cluster", expandCluster);
    const path = `/api/hive-brain/graph?${params}`;
    const result = await apiGet<HiveBrainGraphResponse>(path);
    if (result.ok && result.data?.nodes) {
      setGraph(result.data);
      setMeta({
        source: "live_api",
        lastUpdated: new Date().toISOString(),
        endpoint: path,
        httpStatus: result.status,
      });
    } else {
      setGraph(null);
      setMeta({
        source: "empty",
        lastUpdated: new Date().toISOString(),
        endpoint: path,
        httpStatus: result.status,
        error: result.error || `HTTP ${result.status}`,
      });
    }
    setLoading(false);
  }, [showRaw, expandCluster]);

  useEffect(() => {
    load();
  }, [load]);

  async function openNodeDrawer(nodeId: string) {
    setDrawerLoading(true);
    setDrawerNode(null);
    setLegacyLesson(null);
    const path = `/api/hive-brain/node/${encodeURIComponent(nodeId)}`;
    const result = await apiGet<HiveBrainNodeResponse>(path);
    if (result.ok && result.data?.node) {
      setDrawerNode(result.data.node);
      setDrawerLoading(false);
      return;
    }
    if (nodeId.startsWith("lesson-")) {
      const apiId = lessonNodeIdForApi(nodeId);
      const mem = await apiGet<{ status?: string; node?: LessonDetail }>(
        `/api/memory/node/${encodeURIComponent(apiId)}`
      );
      if (mem.ok && mem.data) {
        const payload = mem.data as { node?: LessonDetail };
        setLegacyLesson(payload.node ?? (mem.data as LessonDetail));
      }
    }
    setDrawerLoading(false);
  }

  const graphMeta = graph?.meta;
  const nodeCount = graph?.nodes?.filter((n) => n.id !== "hive").length ?? 0;
  const showError = !loading && meta.error;
  const showEmpty = !loading && !meta.error && nodeCount === 0;

  return (
    <>
      <GlassPanel
        title={compact ? "Hive Brain" : "Hive Brain — Collective Intelligence"}
        icon={<Network className="h-4 w-4" />}
        action={
          <span className="text-[9px] text-slate-600">
            {meta.source === "live_api" ? "React Flow · live" : meta.source}
          </span>
        }
        className="h-full"
      >
        <div className="flex flex-wrap gap-1 mb-2 items-center">
          <button type="button" onClick={load} className="text-[9px] text-hive-cyan">
            Refresh
          </button>
          <label className="flex items-center gap-1 text-[9px] text-slate-500 cursor-pointer">
            <input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} />
            Raw memories
          </label>
          <button
            type="button"
            disabled={brainBusy}
            className="text-[9px] text-amber-300"
            onClick={async () => {
              setBrainBusy(true);
              await apiPost("/api/hive-brain/consolidate", { force: true });
              await load();
              setBrainBusy(false);
            }}
          >
            Consolidate
          </button>
          <span className="text-[9px] text-slate-600 ml-auto">Click cluster to expand/collapse · pan/zoom/minimap</span>
        </div>
        {graphMeta && (
          <p className="text-[9px] text-slate-600 mb-2 text-center">
            compression {String(graphMeta.compression_ratio ?? "—")} · AI lessons{" "}
            {String(graphMeta.ai_learning_memory_count ?? 0)} · nodes {String(graphMeta.visible_nodes ?? nodeCount)} ·{" "}
            {String(graphMeta.layout_mode ?? "hierarchical")}
          </p>
        )}

        {loading ? (
          <EmptyState message="Loading Hive Brain graph…" className="min-h-[200px]" />
        ) : showError ? (
          <PanelError
            title="Could not load Hive Brain graph"
            meta={meta}
            expectedShape='{ status: "ok", nodes: [...], edges: [...], legend: [...] }'
          />
        ) : showEmpty ? (
          <EmptyState message="No nodes in Hive Brain graph." className="min-h-[200px]" />
        ) : graph ? (
          <>
            <HiveBrainCanvas
              graphNodes={graph.nodes}
              graphEdges={graph.edges}
              legend={graph.legend ?? graph.color_legend}
              shapeLegend={graph.shape_legend}
              onNodeSelect={openNodeDrawer}
              expandCluster={expandCluster}
              onExpandCluster={setExpandCluster}
              heightClass={compact ? "min-h-[280px] h-[280px]" : "min-h-[360px] h-[360px]"}
            />
            <p className="text-[10px] text-slate-500 mt-2 text-center">
              {nodeCount} nodes · pan/zoom · minimap · fit-view · fullscreen · position drawer shows broker proof
            </p>
          </>
        ) : null}
      </GlassPanel>

      <HiveBrainDrawer
        node={drawerNode}
        loading={drawerLoading}
        onClose={() => {
          setDrawerNode(null);
          setDrawerLoading(false);
        }}
      />
      <MemoryLessonDrawer
        detail={legacyLesson}
        onClose={() => setLegacyLesson(null)}
        onUpdated={load}
      />
    </>
  );
}
