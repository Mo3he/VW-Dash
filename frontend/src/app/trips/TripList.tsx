"use client";
import { useState } from "react";
import type { Trip } from "@/lib/types";
import { Zap, Gauge, MapPin, ChevronDown } from "lucide-react";
import clsx from "clsx";
import TripMap from "@/components/TripMap";
import { api } from "@/lib/api";

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

type RouteCache = Record<number, { lat: number; lon: number }[]>;

export default function TripList({ trips, total }: Props) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [routeCache, setRouteCache] = useState<RouteCache>({});

  async function toggleTrip(id: number) {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!routeCache[id]) {
      const data = await api.trips.route(id).catch(() => null);
      if (data) setRouteCache((prev) => ({ ...prev, [id]: data.points }));
    }
  }

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
          className="rounded-2xl bg-[#161b27] border border-white/5 p-4 cursor-pointer"
          onClick={() => toggleTrip(t.id)}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm text-white font-medium">{formatDate(t.started_at)}</div>
          </div>

          {/* Location row */}
          {(t.start_address || t.end_address) && (
            <div className="flex items-start gap-1.5 mb-3 text-xs text-gray-400">
              <MapPin size={12} className="text-[#00B0F0] mt-0.5 shrink-0" />
              <span className="truncate">
                {t.start_address ?? "Unknown"}
                <span className="text-gray-600 mx-1">→</span>
                {t.end_address ?? "Unknown"}
              </span>
            </div>
          )}

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

          <div className="flex items-center justify-between mt-2">
            {t.duration_min != null ? (
              <span className="text-xs text-gray-600">{formatDuration(t.duration_min)}</span>
            ) : <span />}
            <ChevronDown
              size={14}
              className={clsx(
                "text-gray-600 transition-transform",
                expandedId === t.id && "rotate-180"
              )}
            />
          </div>

          {expandedId === t.id && (
            <TripMap
              points={routeCache[t.id] ?? []}
              mapId={`trip-map-${t.id}`}
            />
          )}
        </div>
      ))}
    </div>
  );
}
