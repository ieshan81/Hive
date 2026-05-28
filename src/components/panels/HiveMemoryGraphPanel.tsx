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
import { onHiveNukeComplete } from "@/lib/hiveRefresh";
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
    params.set("mode", "research");
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

  useEffect(() => onHiveNukeComplete(() => {
    setGraph(null);
    setDrawerNode(null);
    setLegacyLesson(null);
    void load();
  }), [load]);

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
  const learnedNodes = Number(graphMeta?.learned_memory_nodes ?? 0);
  const skeletonNodes = Number(graphMeta?.system_skeleton_nodes ?? 0);
  const freshBrain = graph?.fresh_brain === true || graphMeta?.fresh_brain === true;
  const showError = !loading && meta.error;
  const showEmpty = !loading && !meta.error && (freshBrain || learnedNodes === 0);

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
        {graphMeta && !freshBrain && (
          <p className="text-[9px] text-slate-600 mb-2 text-center">
            learned {String(learnedNodes)} · skeleton {String(skeletonNodes)} ·{" "}
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
          <div className="min-h-[200px] flex flex-col items-center justify-center text-center px-4">
            <EmptyState
              message={String(
                graphMeta?.empty_state_headline ?? "Fresh brain. No learned memories yet."
              )}
              className="min-h-0"
            />
            <p className="text-[11px] text-slate-500 mt-2 max-w-md">
              {String(
                graphMeta?.empty_state_subtext ??
                  "Paper learning is available. The next push-pull tick will create new lessons."
              )}
            </p>
          </div>
        ) : graph && !freshBrain ? (
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
              {learnedNodes} learned · pan/zoom · minimap · fit-view · fullscreen
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
