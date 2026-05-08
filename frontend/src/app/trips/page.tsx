import { api } from "@/lib/api";
import StatusCard from "@/components/StatusCard";
import TripList from "./TripList";
import TempEfficiency from "./TempEfficiency";

export const revalidate = 0;

export default async function TripsPage() {
  const [stats, { trips }] = await Promise.all([
    api.trips.stats(30).catch(() => null),
    api.trips.list(20).catch(() => ({ total: 0, trips: [] })),
  ]);

  const sym = stats?.currency_symbol ?? "$";
  const after = stats?.currency_after ?? false;
  const fmtCost = (n: number) =>
    after ? `${n.toFixed(2)} ${sym}` : `${sym}${n.toFixed(2)}`;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-white">Trips</h1>

      {stats && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <StatusCard
              label="Trips (30d)"
              value={stats.trip_count}
            />
            <StatusCard
              label="Distance"
              value={`${stats.total_km.toLocaleString("sv-SE")} km`}
              sub="last 30 days"
            />
            <StatusCard
              label="Energy used"
              value={`${stats.total_kwh} kWh`}
              sub="last 30 days"
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

          {Object.keys(stats.temp_efficiency).length > 0 && (
            <TempEfficiency data={stats.temp_efficiency} />
          )}
        </>
      )}

      <TripList trips={trips} />
    </div>
  );
}
