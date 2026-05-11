export function fmtTime(iso: string, tz: string, hour12 = true): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: tz,
    hour12,
  });
}

export function fmtDate(iso: string, tz: string): string {
  return new Date(iso).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    timeZone: tz,
  });
}

export function fmtDateTime(iso: string, tz: string, hour12 = true): string {
  return new Date(iso).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tz,
    hour12,
  });
}

export function fmtChartTime(iso: string, tz: string, hour12 = true): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tz,
    hour12,
  });
}

export function fmtDist(
  km: number | null | undefined,
  unit: "km" | "miles",
  precomputedMiles?: number | null
): string {
  if (unit === "miles") {
    const m = precomputedMiles != null ? precomputedMiles : km != null ? km * 0.621371 : null;
    return m != null ? `${m.toFixed(1)} mi` : "—";
  }
  return km != null ? `${km.toFixed(1)} km` : "—";
}
