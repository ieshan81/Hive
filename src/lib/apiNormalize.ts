import type {
  ApprovedDecision,
  BlockedDecision,
  DeferredDecision,
  MemoryGraphResponse,
  OrderRecord,
  Position,
  PositionState,
  TradeHistoryRecord,
} from "@/types/api";

/** Extract array from many backend/legacy shapes. */
export function normalizeArrayResponse<T>(
  response: unknown,
  keys: string[] = []
): T[] {
  if (response == null) return [];
  if (Array.isArray(response)) return response as T[];
  if (typeof response !== "object") return [];
  const obj = response as Record<string, unknown>;
  for (const key of keys) {
    const val = obj[key];
    if (Array.isArray(val)) return val as T[];
  }
  if (Array.isArray(obj.data)) return obj.data as T[];
  if (Array.isArray(obj.items)) return obj.items as T[];
  if (Array.isArray(obj.results)) return obj.results as T[];
  return [];
}

export function normalizeMemoryGraph(response: unknown): MemoryGraphResponse {
  if (!response || typeof response !== "object") {
    return { nodes: [], edges: [] };
  }
  const obj = response as Record<string, unknown>;
  const nodes = normalizeArrayResponse<MemoryGraphResponse["nodes"][0]>(obj, ["nodes"]);
  const edges = normalizeArrayResponse<MemoryGraphResponse["edges"][0]>(obj, ["edges"]);
  if (Array.isArray(obj.nodes) && Array.isArray(obj.edges)) {
    return {
      status: typeof obj.status === "string" ? obj.status : undefined,
      nodes: obj.nodes as MemoryGraphResponse["nodes"],
      edges: obj.edges as MemoryGraphResponse["edges"],
    };
  }
  return {
    status: typeof obj.status === "string" ? obj.status : undefined,
    nodes: nodes.length ? nodes : (Array.isArray(obj.nodes) ? (obj.nodes as MemoryGraphResponse["nodes"]) : []),
    edges: edges.length ? edges : (Array.isArray(obj.edges) ? (obj.edges as MemoryGraphResponse["edges"]) : []),
  };
}

export function normalizePositions(response: unknown): Position[] {
  return normalizeArrayResponse<Position>(response, ["positions", "position"]);
}

export function normalizePositionStates(response: unknown): PositionState[] {
  return normalizeArrayResponse<PositionState>(response, ["states", "position_states", "positionStates"]);
}

export function normalizeOrders(response: unknown): OrderRecord[] {
  return normalizeArrayResponse<OrderRecord>(response, ["orders", "order", "execution_logs"]);
}

export function normalizeTrades(response: unknown): TradeHistoryRecord[] {
  return normalizeArrayResponse<TradeHistoryRecord>(response, ["trades", "trade", "trades_history"]);
}

export function normalizeApproved(response: unknown): ApprovedDecision[] {
  return normalizeArrayResponse<ApprovedDecision>(response, [
    "approved",
    "decisions",
    "approved_decisions",
  ]);
}

export function normalizeBlocked(response: unknown): BlockedDecision[] {
  return normalizeArrayResponse<BlockedDecision>(response, [
    "blocked",
    "decisions",
    "blocked_decisions",
    "blocked_trades",
  ]);
}

export function normalizeDeferred(response: unknown): DeferredDecision[] {
  return normalizeArrayResponse<DeferredDecision>(response, [
    "deferred",
    "decisions",
    "deferred_decisions",
  ]);
}

export function normalizeDecisionOrders(response: unknown): unknown[] {
  return normalizeArrayResponse(response, ["orders", "orders_submitted"]);
}

export function normalizeLessons(response: unknown): unknown[] {
  return normalizeArrayResponse(response, ["lessons", "lessons_created"]);
}

/** Generic decision list normalizer by response key. */
export function normalizeDecisions(response: unknown, keys: string[]): unknown[] {
  return normalizeArrayResponse(response, keys);
}

/** Resolve graph node id for lesson detail API. */
export function lessonNodeIdForApi(nodeId: string): string {
  if (nodeId.startsWith("lesson-")) return nodeId;
  if (/^\d+$/.test(nodeId)) return `lesson-${nodeId}`;
  return nodeId;
}

export function isLessonGraphNode(nodeId: string, type?: string): boolean {
  return type === "lesson" || nodeId.startsWith("lesson-");
}
