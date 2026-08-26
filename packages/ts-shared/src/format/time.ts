// Colombo date/time formatting and disaster-relative time labels for the frontend.
// Mirrors packages/py-shared/sarana_shared/domain/time.py. Per
// docs/build-prompts/02-conventions.md: "Never do timezone maths in the frontend" —
// this module formats a UTC ISO string for display, it doesn't compute offsets by hand.

const COLOMBO_TZ = "Asia/Colombo";

export function formatColombo(isoUtc: string, opts?: Intl.DateTimeFormatOptions): string {
  const date = new Date(isoUtc);
  return new Intl.DateTimeFormat("en-LK", {
    timeZone: COLOMBO_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    ...opts,
  }).format(date);
}

/**
 * UTC ISO string -> "T-72h" / "T+0" / "T+14d", relative to landfall — the label used by
 * the design system's time spine (docs/build-prompts/19-design-system.md). Mirrors
 * sarana_shared.domain.time.relative_to_landfall exactly; keep both in sync if either
 * changes.
 */
export function relativeToLandfall(isoUtc: string, landfallIsoUtc: string): string {
  const momentMs = new Date(isoUtc).getTime();
  const landfallMs = new Date(landfallIsoUtc).getTime();
  const totalHours = (momentMs - landfallMs) / (1000 * 60 * 60);
  const sign = totalHours >= 0 ? "+" : "-";
  const magnitude = Math.abs(totalHours);

  if (magnitude === 0) return "T+0";
  if (magnitude <= 72) {
    return `T${sign}${Math.round(magnitude)}h`;
  }
  return `T${sign}${Math.round(magnitude / 24)}d`;
}
