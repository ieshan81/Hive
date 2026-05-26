export type HiveBrainNodeType = "hive" | "cluster" | "lesson" | "position" | "strategy";

export interface HiveBrainGraphNode {
  id: string;
  label: string;
  full_label?: string;
  type: HiveBrainNodeType;
  shape?: string;
  color?: string;
  x?: number;
  y?: number;
  severity?: string;
  confidence?: number;
  status?: string;
  status_ring?: string;
  count?: number;
  source?: string;
  source_table?: string;
  source_endpoint?: string;
  source_id?: string | number | null;
  broker_symbol?: string;
  display_symbol?: string;
  signal_id?: number | null;
  true_hold_minutes?: number | null;
  hold_time_source?: string | null;
  memory_level?: string;
  memory_type?: string;
  visible_by_default?: boolean;
  raw_hidden_by_default?: boolean;
  latest_lesson?: string;
}

export interface HiveBrainGraphEdge {
  id: string;
  source: string;
  target: string;
  relation?: string;
  weight?: number;
  weight_tier?: string;
}

export interface HiveBrainGraphResponse {
  status: string;
  fresh_brain?: boolean;
  center?: HiveBrainGraphNode | null;
  clusters?: { id: string; label: string; shape?: string; color?: string; child_count?: number }[];
  nodes: HiveBrainGraphNode[];
  edges: HiveBrainGraphEdge[];
  legend?: { color: string; meaning: string }[];
  color_legend?: { color: string; meaning: string }[];
  shape_legend?: { shape: string; meaning: string }[];
  meta?: Record<string, unknown>;
}

export interface HiveBrainNodeDrawer {
  id: string;
  title?: string;
  full_label?: string;
  type: string;
  shape?: string;
  summary?: string;
  source?: string;
  source_table?: string;
  source_endpoint?: string;
  source_id?: string | number | null;
  status?: string;
  status_ring?: string;
  sections?: {
    summary?: Record<string, unknown>;
    evidence?: Record<string, unknown>;
    linked_items?: Record<string, unknown>;
  };
}

export interface HiveBrainNodeResponse {
  status: string;
  node?: HiveBrainNodeDrawer;
  message?: string;
}
