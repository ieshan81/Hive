export const COCKPIT_REFRESH = "hive:cockpit-refresh";

export function dispatchCockpitRefresh(detail?: Record<string, unknown>) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(COCKPIT_REFRESH, { detail }));
}
