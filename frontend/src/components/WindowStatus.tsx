"use client";

/**
 * WindowStatus — compact card matching StatusCard style, spans 2 columns.
 * Renders nothing when window data is absent.
 */

const WINDOW_LABELS: Record<string, string> = {
  frontLeft: "FL",
  frontRight: "FR",
  rearLeft: "RL",
  rearRight: "RR",
  sunRoof: "Roof",
  roofCover: "Cover",
  sunRoofRear: "Rear roof",
};

interface WindowEntry {
  open_pct?: number;
  state?: string;
}

interface Props {
  windows: Record<string, WindowEntry> | null | undefined;
}

function isOpen(entry: WindowEntry): boolean {
  if (entry.open_pct != null && entry.open_pct > 0) return true;
  if (entry.state) return entry.state.toLowerCase() === "open";
  return false;
}

export default function WindowStatus({ windows }: Props) {
  if (!windows || Object.keys(windows).length === 0) return null;

  const anyOpen = Object.values(windows).some(isOpen);

  return (
    <div className="rounded-2xl p-4 bg-[#161b27] border border-white/5">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Windows</div>
      <div className={`text-xl font-semibold mb-1.5 ${anyOpen ? "text-yellow-400" : "text-white"}`}>
        {anyOpen ? "Open" : "All closed"}
      </div>
      <div className="flex items-center gap-1 flex-wrap">
        {Object.entries(windows).map(([key, entry]) => {
          const open = isOpen(entry);
          const label = WINDOW_LABELS[key] ?? key;
          const pct = entry.open_pct;
          const detail = pct != null && pct > 0 ? ` ${pct}%` : "";

          return (
            <span
              key={key}
              title={`${key}: ${pct != null ? `${pct}%` : open ? "open" : "closed"}`}
              className={`text-xs px-1.5 py-0.5 rounded-full ${
                open
                  ? "bg-yellow-500/15 text-yellow-400"
                  : "bg-white/5 text-gray-500"
              }`}
            >
              {label}{detail}
            </span>
          );
        })}
      </div>
    </div>
  );
}
