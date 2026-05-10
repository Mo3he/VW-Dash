"use client";
import { useState, useEffect, useCallback } from "react";
import { Download } from "lucide-react";
import { api } from "@/lib/api";
import type { Trip, TripStats } from "@/lib/types";
import StatusCard from "@/components/StatusCard";
import TripList from "./TripList";
import TempEfficiency from "./TempEfficiency";
import EfficiencyChart from "./EfficiencyChart";
import PeriodSelector, { DateRange, defaultRange } from "@/components/PeriodSelector";
import { authHeaders } from "@/lib/auth";

const PAGE_SIZE = 20;

export default function TripsPage() {
  const [stats, setStats] = useState<TripStats | null>(null);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [chartTrips, setChartTrips] = useState<Trip[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [range, setRange] = useState<DateRange>(defaultRange(30));
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const loadStats = useCallback(async () => {
    const s = await api.trips.stats(range.start, range.end).catch(() => null);
    setStats(s);
  }, [range]);

  const loadTrips = useCallback(async (off: number, append: boolean) => {
    const data = await api.trips
      .list(PAGE_SIZE, off, range.start, range.end)
      .catch(() => ({ total: 0, trips: [] as Trip[] }));
    if (append) {
      setTrips((prev) => [...prev, ...data.trips]);
    } else {
      setTrips(data.trips);
    }
    setTotal(data.total);
    setOffset(off + data.trips.length);
  }, [range]);

  const loadChartTrips = useCallback(async () => {
    const data = await api.trips
      .list(1000, 0, range.start, range.end)
      .catch(() => ({ trips: [] as Trip[] }));
    setChartTrips(data.trips);
  }, [range]);

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

  function pctDelta(current: number, prev: number | undefined): number | null {
    if (prev == null || prev === 0) return null;
    return ((current - prev) / prev) * 100;
  }

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
        <div className="flex items-center gap-2">
          <a
            href={`/api/trips/export.csv?start_date=${range.start}&end_date=${range.end}`}
            onClick={async (e) => {
              const token = authHeaders().Authorization;
              if (!token) return;
              e.preventDefault();
              const res = await fetch(`/api/trips/export.csv?start_date=${range.start}&end_date=${range.end}`, { headers: authHeaders() });
              const blob = await res.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url; a.download = "trips.csv"; a.click();
              URL.revokeObjectURL(url);
            }}
            download="trips.csv"
            title="Export CSV"
            className="p-1.5 text-gray-500 hover:text-gray-300 transition"
          >
            <Download size={16} />
          </a>
          <PeriodSelector value={range} onChange={setRange} />
        </div>
      </div>

      {stats && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <StatusCard
              label="Trips"
              value={stats.trip_count}
              delta={pctDelta(stats.trip_count, stats.prev?.trip_count)}
            />
            <StatusCard
              label="Distance"
              value={`${stats.total_km.toLocaleString("sv-SE")} km`}
              delta={pctDelta(stats.total_km, stats.prev?.total_km)}
            />
            <StatusCard
              label="Energy used"
              value={`${stats.total_kwh} kWh`}
              delta={pctDelta(stats.total_kwh, stats.prev?.total_kwh)}
              deltaInvert
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
            {stats.total_km > 0 && (() => {
              // CO₂ saved vs equivalent petrol car (7L/100km, 2.31 kg CO₂/L)
              // minus grid emissions (0.233 kg CO₂/kWh)
              const petrolCo2 = (stats.total_km / 100) * 7 * 2.31;
              const gridCo2 = stats.total_kwh * 0.233;
              const saved = Math.max(0, petrolCo2 - gridCo2);
              return (
                <StatusCard
                  label="CO₂ saved vs petrol"
                  value={saved >= 1000 ? `${(saved / 1000).toFixed(2)} t` : `${saved.toFixed(1)} kg`}
                  sub="vs 7L/100km car"
                />
              );
            })()}
          </div>

          {chartTrips.length > 1 && <EfficiencyChart trips={chartTrips} />}

          {Object.keys(stats.temp_efficiency).length > 0 && (
            <TempEfficiency data={stats.temp_efficiency} />
          )}
        </>
      )}

      <TripList
        trips={trips}
        total={total}
        onDelete={(id) => {
          setTrips((prev) => prev.filter((t) => t.id !== id));
          setTotal((n) => n - 1);
        }}
      />

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
