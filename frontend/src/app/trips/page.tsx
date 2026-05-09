"use client";
import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { Trip, TripStats } from "@/lib/types";
import StatusCard from "@/components/StatusCard";
import TripList from "./TripList";
import TempEfficiency from "./TempEfficiency";
import EfficiencyChart from "./EfficiencyChart";
import PeriodSelector from "@/components/PeriodSelector";

const PAGE_SIZE = 20;

function periodLabel(days: number) {
  return days >= 3650 ? "all time" : `last ${days} days`;
}

export default function TripsPage() {
  const [stats, setStats] = useState<TripStats | null>(null);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [chartTrips, setChartTrips] = useState<Trip[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statsDays, setStatsDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const loadStats = useCallback(async () => {
    const s = await api.trips.stats(statsDays).catch(() => null);
    setStats(s);
  }, [statsDays]);

  const loadTrips = useCallback(async (off: number, append: boolean) => {
    const data = await api.trips
      .list(PAGE_SIZE, off, statsDays)
      .catch(() => ({ total: 0, trips: [] as Trip[] }));
    if (append) {
      setTrips((prev) => [...prev, ...data.trips]);
    } else {
      setTrips(data.trips);
    }
    setTotal(data.total);
    setOffset(off + data.trips.length);
  }, [statsDays]);

  const loadChartTrips = useCallback(async () => {
    const data = await api.trips
      .list(1000, 0, statsDays)
      .catch(() => ({ trips: [] as Trip[] }));
    setChartTrips(data.trips);
  }, [statsDays]);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadStats(), loadTrips(0, false), loadChartTrips()]).finally(
      () => setLoading(false)
    );
  }, [loadStats, loadTrips, loadChartTrips]);

  async function handleLoadMore() {
    setLoadingMore(true);
    await loadTrips(offset, true);
    setLoadingMore(false);
  }

  const sym = stats?.currency_symbol ?? "$";
  const after = stats?.currency_after ?? false;
  const fmtCost = (n: number) =>
    after ? `${n.toFixed(2)} ${sym}` : `${sym}${n.toFixed(2)}`;

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-lg font-semibold text-white">Trips</h1>
        <div className="text-center text-gray-500 py-8">Loading…</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-white">Trips</h1>
        <PeriodSelector value={statsDays} onChange={setStatsDays} />
      </div>

      {stats && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <StatusCard
              label={`Trips (${periodLabel(statsDays)})`}
              value={stats.trip_count}
            />
            <StatusCard
              label="Distance"
              value={`${stats.total_km.toLocaleString("sv-SE")} km`}
              sub={periodLabel(statsDays)}
            />
            <StatusCard
              label="Energy used"
              value={`${stats.total_kwh} kWh`}
              sub={periodLabel(statsDays)}
            />
            <StatusCard
              label="Avg efficiency"
              value={
                stats.avg_efficiency_kwh_100km != null
                  ? `${stats.avg_efficiency_kwh_100km} kWh/100km`
                  : "—"
              }
            />
            <StatusCard
              label="Cost per 100km"
              value={
                stats.cost_per_100km != null
                  ? fmtCost(stats.cost_per_100km)
                  : "—"
              }
            />
          </div>

          {chartTrips.length > 1 && <EfficiencyChart trips={chartTrips} />}

          {Object.keys(stats.temp_efficiency).length > 0 && (
            <TempEfficiency data={stats.temp_efficiency} />
          )}
        </>
      )}

      <TripList trips={trips} total={total} />

      {trips.length < total && (
        <button
          onClick={handleLoadMore}
          disabled={loadingMore}
          className="w-full rounded-xl border border-white/10 py-2.5 text-sm text-gray-400
            hover:text-white hover:border-white/20 disabled:opacity-50 transition"
        >
          {loadingMore ? "Loading…" : `Load more (${total - trips.length} remaining)`}
        </button>
      )}
    </div>
  );
}
