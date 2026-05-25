"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Maximize2, Minimize2, ZoomIn, LayoutGrid } from "lucide-react";

import { HiveBrainCustomNode, type HiveBrainNodeData } from "@/components/hive-brain/HiveBrainCustomNode";
import type { HiveBrainGraphNode, HiveBrainGraphEdge } from "@/types/hiveBrain";

const nodeTypes = { hiveBrain: HiveBrainCustomNode } as const;
const SCALE = 10;

function toFlowPosition(x?: number, y?: number) {
  return { x: ((x ?? 50) - 50) * SCALE, y: ((y ?? 50) - 50) * SCALE };
}

function graphToFlow(
  nodes: HiveBrainGraphNode[],
  edges: HiveBrainGraphEdge[],
  collapsedClusters: Set<string>
): { nodes: Node<HiveBrainNodeData>[]; edges: Edge[] } {
  const visibleIds = new Set<string>();
  for (const n of nodes) {
    if (n.type === "hive" || n.type === "cluster" || n.type === "position" || n.type === "strategy") {
      visibleIds.add(n.id);
      continue;
    }
    if (n.type === "lesson") {
      const clusterEdge = edges.find((e) => e.target === n.id && e.source.startsWith("cluster-"));
      const clusterId = clusterEdge?.source;
      if (!clusterId || !collapsedClusters.has(clusterId)) visibleIds.add(n.id);
    } else {
      visibleIds.add(n.id);
    }
  }

  const flowNodes: Node<HiveBrainNodeData>[] = nodes
    .filter((n) => visibleIds.has(n.id))
    .map((n) => {
      const pos = toFlowPosition(n.x, n.y);
      return {
        id: n.id,
        type: "hiveBrain",
        position: pos,
        data: {
          label: n.label,
          fullLabel: n.full_label || n.label,
          nodeType: n.type,
          shape: n.shape,
          color: n.color,
          statusRing: n.status_ring,
          severity: n.severity,
          count: n.count,
          source: n.source,
          trueHoldMinutes: n.true_hold_minutes ?? null,
        },
      };
    });

  const flowEdges: Edge[] = edges
    .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      animated: e.weight_tier === "strong",
      style: {
        stroke: e.weight_tier === "strong" ? "#22d3ee" : "#64748b",
        strokeWidth: e.weight_tier === "strong" ? 2 : 1,
        opacity: 0.65,
      },
      label: e.relation,
      labelStyle: { fill: "#94a3b8", fontSize: 8 },
    }));

  return { nodes: flowNodes, edges: flowEdges };
}

interface InnerProps {
  graphNodes: HiveBrainGraphNode[];
  graphEdges: HiveBrainGraphEdge[];
  legend?: { color: string; meaning: string }[];
  shapeLegend?: { shape: string; meaning: string }[];
  onNodeSelect: (nodeId: string) => void;
  expandCluster?: string | null;
  onExpandCluster?: (clusterId: string | null) => void;
  heightClass?: string;
}

function HiveBrainFlowInner({
  graphNodes,
  graphEdges,
  legend,
  shapeLegend,
  onNodeSelect,
  expandCluster,
  onExpandCluster,
  heightClass = "min-h-[320px]",
}: InnerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { fitView, zoomIn } = useReactFlow();
  const [fullscreen, setFullscreen] = useState(false);
  const [collapsedClusters, setCollapsedClusters] = useState<Set<string>>(() => new Set());

  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => graphToFlow(graphNodes, graphEdges, collapsedClusters),
    [graphNodes, graphEdges, collapsedClusters]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    const { nodes: n, edges: e } = graphToFlow(graphNodes, graphEdges, collapsedClusters);
    setNodes(n);
    setEdges(e);
    const t = setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 80);
    return () => clearTimeout(t);
  }, [graphNodes, graphEdges, collapsedClusters, setNodes, setEdges, fitView]);

  useEffect(() => {
    const onFs = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  const toggleFullscreen = useCallback(async () => {
    const el = containerRef.current;
    if (!el) return;
    if (!document.fullscreenElement) await el.requestFullscreen();
    else await document.exitFullscreen();
  }, []);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const d = node.data as HiveBrainNodeData;
      const nt = d?.nodeType;
      if (nt === "cluster") {
        const id = node.id;
        if (collapsedClusters.has(id)) {
          const next = new Set(collapsedClusters);
          next.delete(id);
          setCollapsedClusters(next);
          onExpandCluster?.(id);
        } else {
          const next = new Set(collapsedClusters);
          next.add(id);
          setCollapsedClusters(next);
          onExpandCluster?.(null);
        }
        return;
      }
      onNodeSelect(node.id);
    },
    [collapsedClusters, onNodeSelect, onExpandCluster]
  );

  return (
    <div
      ref={containerRef}
      className={`relative w-full rounded-xl border border-white/5 bg-[#030508] ${heightClass} ${
        fullscreen ? "h-screen min-h-screen" : ""
      }`}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        fitView
        minZoom={0.2}
        maxZoom={2}
        panOnDrag
        panOnScroll
        zoomOnScroll
        zoomOnPinch
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1e293b" gap={16} />
        <Controls showInteractive={false} className="!bg-slate-900/90 !border-white/10" />
        <MiniMap
          nodeColor={(n) => (n.data as HiveBrainNodeData)?.color || "#334155"}
          maskColor="rgba(3,5,8,0.85)"
          className="!bg-slate-900/80 !border-white/10"
        />
        <Panel position="top-right" className="flex gap-1">
          <button
            type="button"
            title="Fit view"
            onClick={() => fitView({ padding: 0.2, duration: 300 })}
            className="p-1.5 rounded bg-slate-800/90 border border-white/10 text-slate-300 hover:text-cyan-300"
          >
            <LayoutGrid className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="Zoom in"
            onClick={() => zoomIn({ duration: 200 })}
            className="p-1.5 rounded bg-slate-800/90 border border-white/10 text-slate-300 hover:text-cyan-300"
          >
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title={fullscreen ? "Exit fullscreen" : "Fullscreen"}
            onClick={toggleFullscreen}
            className="p-1.5 rounded bg-slate-800/90 border border-white/10 text-slate-300 hover:text-cyan-300"
          >
            {fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
        </Panel>
        {(legend?.length || shapeLegend?.length) && (
          <Panel position="bottom-left" className="max-w-[200px] p-2 rounded-lg bg-slate-900/90 border border-white/10 text-[8px] text-slate-400">
            {legend?.slice(0, 4).map((l) => (
              <div key={l.meaning} className="flex items-center gap-1 mb-0.5">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: l.color }} />
                {l.meaning}
              </div>
            ))}
          </Panel>
        )}
      </ReactFlow>
      {expandCluster && (
        <p className="absolute bottom-2 right-2 text-[9px] text-violet-300">Expanded: {expandCluster}</p>
      )}
    </div>
  );
}

interface CanvasProps extends InnerProps {}

export function HiveBrainCanvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <HiveBrainFlowInner {...props} />
    </ReactFlowProvider>
  );
}
