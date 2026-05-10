export function fmtTime(iso: string, tz: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: tz,
  });
}

export function fmtDate(iso: string, tz: string): string {
  return new Date(iso).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    timeZone: tz,
  });
}

export function fmtDateTime(iso: string, tz: string): string {
  return new Date(iso).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tz,
  });
}

export function fmtChartTime(iso: string, tz: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tz,
  });
}
