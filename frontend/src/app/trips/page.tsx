"use client";
import { useState, useEffect, useCallback } from "react";
import { Download, Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Trip, TripStats } from "@/lib/types";
import StatusCard from "@/components/StatusCard";
import TripList from "./TripList";
import TempEfficiency from "./TempEfficiency";
import EfficiencyChart from "./EfficiencyChart";
import PeriodSelector, { DateRange, defaultRange } from "@/components/PeriodSelector";
import { authHeaders } from "@/lib/auth";
import { useDistanceUnit } from "@/app/SettingsProvider";

const PAGE_SIZE = 20;

interface AddTripForm {
  started_at: string;
  ended_at: string;
  distance_km: string;
  soc_start_pct: string;
  soc_end_pct: string;
}

function toLocalDatetimeValue(isoOrEmpty: string): string {
  if (!isoOrEmpty) return "";
  // datetime-local inputs expect "YYYY-MM-DDTHH:mm"
  return isoOrEmpty.slice(0, 16);
}

function localDatetimeToISO(value: string): string {
  // Convert the datetime-local value to an ISO string (treat as UTC)
  if (!value) return "";
  return new Date(value).toISOString();
}

export default function TripsPage() {
  const [stats, setStats] = useState<TripStats | null>(null);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [chartTrips, setChartTrips] = useState<Trip[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [range, setRange] = useState<DateRange>(defaultRange(30));
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [addForm, setAddForm] = useState<AddTripForm>({ started_at: "", ended_at: "", distance_km: "", soc_start_pct: "", soc_end_pct: "" });
  const [addError, setAddError] = useState<string | null>(null);
  const [addSaving, setAddSaving] = useState(false);

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

  async function handleAddTrip(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    setAddSaving(true);
    try {
      const body: Parameters<typeof api.trips.create>[0] = {
        started_at: localDatetimeToISO(addForm.started_at),
        ended_at: localDatetimeToISO(addForm.ended_at),
        distance_km: parseFloat(addForm.distance_km),
      };
      if (addForm.soc_start_pct) body.soc_start_pct = parseFloat(addForm.soc_start_pct);
      if (addForm.soc_end_pct) body.soc_end_pct = parseFloat(addForm.soc_end_pct);
      const created = await api.trips.create(body);
      setTrips((prev) => [created, ...prev]);
      setTotal((n) => n + 1);
      setShowAddModal(false);
      setAddForm({ started_at: "", ended_at: "", distance_km: "", soc_start_pct: "", soc_end_pct: "" });
      loadStats();
    } catch (err: unknown) {
      setAddError(err instanceof Error ? err.message : "Failed to save trip");
    } finally {
      setAddSaving(false);
    }
  }

  const sym = stats?.currency_symbol ?? "$";
  const after = stats?.currency_after ?? false;
  const fmtCost = (n: number) =>
    after ? `${n.toFixed(2)} ${sym}` : `${sym}${n.toFixed(2)}`;

  const distanceUnit = useDistanceUnit();

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
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            title="Add trip"
            className="p-1.5 text-gray-500 hover:text-gray-300 transition"
          >
            <Plus size={16} />
          </button>
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
              value={distanceUnit === "miles"
                ? `${(stats.total_km * 0.621371).toLocaleString("sv-SE", { maximumFractionDigits: 0 })} mi`
                : `${stats.total_km.toLocaleString("sv-SE")} km`}
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
                  ? distanceUnit === "miles"
                    ? `${(stats.avg_efficiency_kwh_100km * 1.60934).toFixed(1)} kWh/100mi`
                    : `${stats.avg_efficiency_kwh_100km} kWh/100km`
                  : "—"
              }
            />
            <StatusCard
              label={distanceUnit === "miles" ? "Cost per 100mi" : "Cost per 100km"}
              value={
                stats.cost_per_100km != null
                  ? distanceUnit === "miles"
                    ? fmtCost(stats.cost_per_100km * 1.60934)
                    : fmtCost(stats.cost_per_100km)
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

      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-[#161b27] border border-white/10 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-white">Add trip</h2>
              <button type="button" onClick={() => setShowAddModal(false)} className="text-gray-500 hover:text-white">
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleAddTrip} className="flex flex-col gap-3">
              <div>
                <label className="text-xs text-gray-400 block mb-1">Start time</label>
                <input
                  type="datetime-local"
                  required
                  value={addForm.started_at}
                  onChange={(e) => setAddForm((f) => ({ ...f, started_at: e.target.value }))}
                  className="w-full rounded-lg bg-[#0d1117] border border-white/10 px-3 py-1.5 text-sm text-white focus:outline-none focus:border-[#00B0F0]/50"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">End time</label>
                <input
                  type="datetime-local"
                  required
                  value={addForm.ended_at}
                  onChange={(e) => setAddForm((f) => ({ ...f, ended_at: e.target.value }))}
                  className="w-full rounded-lg bg-[#0d1117] border border-white/10 px-3 py-1.5 text-sm text-white focus:outline-none focus:border-[#00B0F0]/50"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">Distance (km)</label>
                <input
                  type="number"
                  required
                  min="0.1"
                  step="0.1"
                  value={addForm.distance_km}
                  onChange={(e) => setAddForm((f) => ({ ...f, distance_km: e.target.value }))}
                  className="w-full rounded-lg bg-[#0d1117] border border-white/10 px-3 py-1.5 text-sm text-white focus:outline-none focus:border-[#00B0F0]/50"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-400 block mb-1">SoC start %</label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={addForm.soc_start_pct}
                    onChange={(e) => setAddForm((f) => ({ ...f, soc_start_pct: e.target.value }))}
                    className="w-full rounded-lg bg-[#0d1117] border border-white/10 px-3 py-1.5 text-sm text-white focus:outline-none focus:border-[#00B0F0]/50"
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-400 block mb-1">SoC end %</label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={addForm.soc_end_pct}
                    onChange={(e) => setAddForm((f) => ({ ...f, soc_end_pct: e.target.value }))}
                    className="w-full rounded-lg bg-[#0d1117] border border-white/10 px-3 py-1.5 text-sm text-white focus:outline-none focus:border-[#00B0F0]/50"
                  />
                </div>
              </div>
              {addError && <p className="text-xs text-red-400">{addError}</p>}
              <button
                type="submit"
                disabled={addSaving}
                className="mt-1 w-full rounded-lg bg-[#00B0F0]/20 text-[#00B0F0] py-2 text-sm font-medium
                  hover:bg-[#00B0F0]/30 disabled:opacity-50 transition"
              >
                {addSaving ? "Saving…" : "Add trip"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
