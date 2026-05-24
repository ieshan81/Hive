/** Format ISO UTC timestamps for display (browser local time + UTC label). */
export function formatSyncTime(isoUtc: string | null | undefined): string {
  if (!isoUtc) return "Not synced";
  const date = new Date(isoUtc);
  if (Number.isNaN(date.getTime())) return isoUtc;

  const local = date.toLocaleString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    month: "short",
    day: "numeric",
  });
  const utc = date.toLocaleString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  });

  return `${local} local · ${utc} UTC`;
}

export function formatShortTime(isoUtc: string | null | undefined): string {
  if (!isoUtc) return "—";
  const date = new Date(isoUtc);
  if (Number.isNaN(date.getTime())) return isoUtc;
  return date.toLocaleString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}
