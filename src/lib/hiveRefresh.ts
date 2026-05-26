/** Cross-panel refresh after NUKE or bootstrap repair. */

export const HIVE_NUKE_COMPLETE_EVENT = "hive-nuke-complete";

export function dispatchHiveNukeComplete(detail?: Record<string, unknown>) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(HIVE_NUKE_COMPLETE_EVENT, { detail }));
}

export function onHiveNukeComplete(handler: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const wrapped = () => handler();
  window.addEventListener(HIVE_NUKE_COMPLETE_EVENT, wrapped);
  return () => window.removeEventListener(HIVE_NUKE_COMPLETE_EVENT, wrapped);
}
