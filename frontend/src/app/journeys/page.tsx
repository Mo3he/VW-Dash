"use client";
import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { Journey, PopularRoute } from "@/lib/types";
import { MapPin, ChevronDown } from "lucide-react";
import PeriodSelector, { DateRange, defaultRange } from "@/components/PeriodSelector";
import JourneyMap from "@/components/JourneyMap";

type RouteCache = Record<string, { lat: number; lon: number }[][]>;


export default function JourneysPage() {
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [popular, setPopular] = useState<PopularRoute[]>([]);
  const [range, setRange] = useState<DateRange>(defaultRange(30));
  const [loading, setLoading] = useState(true);
  const [expandedJourney, setExpandedJourney] = useState<string | null>(null);
  const [routeCache, setRouteCache] = useState<RouteCache>({});

  const load = useCallback(async () => {
    setLoading(true);
    await Promise.all([
      api.trips.journeys(range.start, range.end).then(setJourneys).catch(() => {}),
      api.trips.popular().then(setPopular).catch(() => {}),
    ]);
    setLoading(false);
  }, [range]);

  useEffect(() => { load(); }, [load]);

  async function toggleJourney(j: Journey) {
    const date = j.date;
    if (expandedJourney === date) {
      setExpandedJourney(null);
      return;
    }
    setExpandedJourney(date);
    if (!routeCache[date]) {
      const results = await Promise.all(
        j.trips.map((t) => api.trips.route(t.id).catch(() => null))
      );
      const routes = results
        .filter(Boolean)
        .map((r) => r!.points);
      setRouteCache((prev) => ({ ...prev, [date]: routes }));
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-lg font-semibold text-white">Journeys</h1>
        <div className="text-center text-gray-500 py-8">Loading…</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-white">Journeys</h1>
        <PeriodSelector value={range} onChange={setRange} />
      </div>

      {popular.length > 0 && (
        <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">
            Most popular routes
          </div>
          <div className="flex flex-col divide-y divide-white/5">
            {popular.map((r, i) => (
              <div key={i} className="flex items-center gap-3 py-2 first:pt-0 last:pb-0">
                <span className="text-xs text-gray-600 w-4 shrink-0">{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1 text-xs text-white">
                    <MapPin size={10} className="text-[#00B0F0] shrink-0" />
                    <span className="truncate">{r.start}</span>
                    <span className="text-gray-600 mx-0.5">→</span>
                    <span className="truncate">{r.end}</span>
                  </div>
                  {r.avg_distance_km && (
                    <div className="text-xs text-gray-500 mt-0.5">{r.avg_distance_km} km avg</div>
                  )}
                </div>
                <div className="text-xs text-[#00B0F0] shrink-0">{r.count}×</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {journeys.length === 0 ? (
        <div className="rounded-2xl bg-[#161b27] border border-white/5 p-6 text-center text-gray-500">
          No journey data yet — location addresses populate as trips are recorded.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {journeys.map((j) => (
            <div key={j.date} className="rounded-2xl bg-[#161b27] border border-white/5 overflow-hidden">
              <button
                className="w-full flex items-center gap-3 p-4 text-left hover:bg-white/5 transition"
                onClick={() => toggleJourney(j)}
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-white">{j.date}</div>
                  {(j.start_address || j.end_address) && (
                    <div className="text-xs text-gray-500 truncate mt-0.5">
                      {j.start_address} → {j.end_address}
                    </div>
                  )}
                </div>
                <div className="text-xs text-gray-400 shrink-0 text-right mr-1">
                  <div className="text-sm font-medium text-white">{j.total_km} km</div>
                  <div className="text-gray-500 mt-0.5">{j.trip_count} trip{j.trip_count !== 1 ? "s" : ""} · {j.total_kwh} kWh</div>
                </div>
                <ChevronDown
                  size={14}
                  className={`text-gray-600 shrink-0 transition-transform ${expandedJourney === j.date ? "rotate-180" : ""}`}
                />
              </button>
              {expandedJourney === j.date && (
                <div className="border-t border-white/5">
                  {routeCache[j.date] && routeCache[j.date].some((r) => r.length >= 2) && (
                    <div className="px-4 pt-3">
                      <JourneyMap
                        routes={routeCache[j.date]}
                        mapId={`journey-map-${j.date}`}
                      />
                    </div>
                  )}
                  <div className="divide-y divide-white/5">
                  {j.trips.map((t) => (
                    <div key={t.id} className="flex items-center gap-3 px-4 py-3">
                      <div className="flex-1 min-w-0">
                        <div className="text-xs text-gray-300 truncate">
                          {t.start_address ?? "—"} → {t.end_address ?? "—"}
                        </div>
                        {t.distance_km != null && (
                          <div className="text-xs text-gray-600 mt-0.5">
                            {t.distance_km.toFixed(1)} km
                            {t.kwh_used != null && ` · ${t.kwh_used} kWh`}
                          </div>
                        )}
                      </div>
                      {t.duration_min != null && (
                        <div className="text-xs text-gray-500 shrink-0">
                          {t.duration_min < 60 ? `${t.duration_min}m` : `${Math.floor(t.duration_min / 60)}h ${t.duration_min % 60}m`}
                        </div>
                      )}
                    </div>
                  ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
