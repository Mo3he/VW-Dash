import { api } from "@/lib/api";
import StatusCard from "@/components/StatusCard";
import ChargingSessionList from "./ChargingSessionList";

export const revalidate = 0;

export default async function ChargingPage() {
  const [stats, { sessions }] = await Promise.all([
    api.charging.stats(30).catch(() => null),
    api.charging.sessions(20).catch(() => ({ total: 0, sessions: [] })),
  ]);

  const sym = stats?.currency_symbol ?? "$";
  const after = stats?.currency_after ?? false;
  const fmtCost = (n: number) =>
    after ? `${n.toFixed(2)} ${sym}` : `${sym}${n.toFixed(2)}`;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-white">Charging</h1>

      {stats && (
        <div className="grid grid-cols-2 gap-3">
          <StatusCard
            label="Sessions (30d)"
            value={stats.session_count}
          />
          <StatusCard
            label="Energy added"
            value={`${stats.total_kwh} kWh`}
            sub="last 30 days"
          />
          <StatusCard
            label="Estimated cost"
            value={fmtCost(stats.total_cost)}
            sub={`@ ${fmtCost(stats.electricity_rate)}/kWh`}
          />
          <StatusCard
            label="Range added"
            value={`${stats.total_range_km} km`}
            sub="last 30 days"
          />
          <StatusCard
            label="DC fast charges"
            value={stats.dc_session_count}
            sub="last 30 days"
          />
          <StatusCard
            label="Avg per session"
            value={`${stats.avg_kwh_per_session} kWh`}
          />
        </div>
      )}

      <ChargingSessionList sessions={sessions} />
    </div>
  );
}
