"use client";
import type { Trip } from "@/lib/types";
import { Thermometer, Zap, Gauge } from "lucide-react";
import clsx from "clsx";

interface Props {
  trips: Trip[];
  total: number;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(min: number | null) {
  if (min == null) return null;
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function efficiencyColor(kwh: number | null): string {
  if (kwh == null) return "text-white";
  if (kwh < 16) return "text-green-400";
  if (kwh < 20) return "text-[#00B0F0]";
  if (kwh < 25) return "text-yellow-400";
  return "text-red-400";
}

export default function TripList({ trips, total }: Props) {
  if (!trips.length) {
    return (
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-6 text-center text-gray-500">
        No trips recorded yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-gray-500 uppercase tracking-wider px-1">
        All trips ({total})
      </div>
      {trips.map((t) => (
        <div
          key={t.id}
          className="rounded-2xl bg-[#161b27] border border-white/5 p-4"
        >
          <div className="flex items-center justify-between mb-3">
            <div className="text-sm text-white font-medium">{formatDate(t.started_at)}</div>
            {t.outdoor_temp_c != null && (
              <span className="flex items-center gap-1 text-xs text-gray-500">
                <Thermometer size={12} />
                {t.outdoor_temp_c.toFixed(1)}°C
              </span>
            )}
          </div>

          {/* Primary metrics row */}
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <div className="text-lg font-semibold text-white">
                {t.distance_km != null ? t.distance_km.toFixed(1) : "—"}
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
              <div className={clsx("text-lg font-semibold", efficiencyColor(t.efficiency_kwh_100km))}>
                {t.efficiency_kwh_100km != null ? t.efficiency_kwh_100km : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">kWh/100km</div>
            </div>
          </div>

          {/* Secondary metrics row */}
          <div className="grid grid-cols-2 gap-3 text-center mt-3">
            <div>
              <div className="flex items-center justify-center gap-1 text-sm font-medium text-white">
                <Zap size={13} className="text-yellow-400" />
                {t.kwh_used != null ? `${t.kwh_used} kWh` : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">Energy used</div>
            </div>
            <div>
              <div className="flex items-center justify-center gap-1 text-sm font-medium text-white">
                <Gauge size={13} className="text-gray-400" />
                {t.avg_speed_kmh != null ? `${Math.round(t.avg_speed_kmh)} km/h` : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">Avg speed</div>
            </div>
          </div>

          {t.duration_min != null && (
            <div className="text-xs text-gray-600 mt-2 text-right">
              {formatDuration(t.duration_min)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
