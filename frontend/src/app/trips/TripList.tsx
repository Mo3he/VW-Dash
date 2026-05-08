"use client";
import type { Trip } from "@/lib/types";
import { Thermometer } from "lucide-react";

interface Props {
  trips: Trip[];
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function TripList({ trips }: Props) {
  if (!trips.length) {
    return (
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-6 text-center text-gray-500">
        No trips recorded yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-gray-500 uppercase tracking-wider px-1">Recent trips</div>
      {trips.map((t) => (
        <div
          key={t.id}
          className="rounded-2xl bg-[#161b27] border border-white/5 p-4"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm text-white font-medium">{formatDate(t.started_at)}</div>
            {t.outdoor_temp_c != null && (
              <span className="flex items-center gap-1 text-xs text-gray-500">
                <Thermometer size={12} />
                {t.outdoor_temp_c.toFixed(1)}°C
              </span>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <div className="text-lg font-semibold text-white">
                {t.distance_km != null ? `${t.distance_km.toFixed(1)}` : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">km</div>
            </div>
            <div>
              <div className="text-lg font-semibold text-white">
                {t.soc_start_pct != null ? `${Math.round(t.soc_start_pct)}%` : "—"}
                <span className="text-gray-500 mx-1">→</span>
                {t.soc_end_pct != null ? `${Math.round(t.soc_end_pct)}%` : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">SoC</div>
            </div>
            <div>
              <div className="text-lg font-semibold text-[#00B0F0]">
                {t.efficiency_kwh_100km != null ? `${t.efficiency_kwh_100km}` : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">kWh/100km</div>
            </div>
          </div>

          {t.duration_min != null && (
            <div className="text-xs text-gray-600 mt-2 text-right">
              {t.duration_min} min
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
