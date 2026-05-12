"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { MonthlyStats } from "@/lib/types";
import { useDistanceUnit } from "@/app/SettingsProvider";

function fmtDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h < 24) return m > 0 ? `${h}.${Math.round((m / 60) * 10)}h` : `${h}h`;
  const days = (minutes / 60 / 24).toFixed(2);
  return `${days} days`;
}

function fmtCost(cost: number, symbol: string, after: boolean): string {
  if (cost === 0) return `${after ? "" : symbol}0.00${after ? symbol : ""}`;
  return after
    ? `${cost.toFixed(2)}${symbol}`
    : `${symbol}${cost.toFixed(2)}`;
}

export default function StatsPage() {
  const [rows, setRows] = useState<MonthlyStats[] | null>(null);
  const [loading, setLoading] = useState(true);
  const distanceUnit = useDistanceUnit();

  useEffect(() => {
    api.stats
      .monthly()
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, []);

  const th =
    "px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-white/40 whitespace-nowrap";
  const td = "px-3 py-2.5 text-sm text-white whitespace-nowrap";
  const tdNum = `${td} tabular-nums text-right`;

  return (
    <main className="p-4 md:p-6 max-w-full mx-auto">
      <h1 className="text-xl font-semibold text-white mb-4">
        Statistics <span className="text-gray-500 font-normal text-base">(per month)</span>
      </h1>

      {loading ? (
        <div className="text-gray-500 text-sm">Loading…</div>
      ) : !rows || rows.length === 0 ? (
        <div className="text-gray-500 text-sm">No data yet.</div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-white/5">
          <table className="w-full border-collapse bg-[#161b27]">
            <thead>
              <tr className="border-b border-white/5">
                <th className={th}>Period</th>
                <th className={`${th} text-right`}># Drives</th>
                <th className={`${th} text-right`}>Time driven</th>
                <th className={`${th} text-right`}>Distance</th>
                <th className={`${th} text-right`}>Median D</th>
                <th className={`${th} text-right`}># Charges</th>
                <th className={`${th} text-right`}>Time charging</th>
                <th className={`${th} text-right`}>Avg. charging</th>
                <th className={`${th} text-right`}>Energy charged</th>
                <th className={`${th} text-right`}>Avg. charged</th>
                <th className={`${th} text-right`}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const dist =
                  distanceUnit === "miles"
                    ? `${(row.distance_km * 0.621371).toFixed(0)} mi`
                    : `${row.distance_km} km`;
                const medDist =
                  row.median_distance_km == null
                    ? "—"
                    : distanceUnit === "miles"
                    ? `${(row.median_distance_km * 0.621371).toFixed(1)} mi`
                    : `${row.median_distance_km} km`;

                return (
                  <tr
                    key={row.period_key}
                    className={
                      i % 2 === 0
                        ? "border-b border-white/5"
                        : "bg-white/5 border-b border-white/5"
                    }
                  >
                    <td className={`${td} font-medium`}>{row.period}</td>
                    <td className={tdNum}>{row.drive_count}</td>
                    <td className={tdNum}>{fmtDuration(row.time_driven_min)}</td>
                    <td className={tdNum}>{dist}</td>
                    <td className={tdNum}>{medDist}</td>
                    <td className={tdNum}>{row.charge_count}</td>
                    <td className={tdNum}>{fmtDuration(row.time_charging_min)}</td>
                    <td className={tdNum}>
                      {row.avg_charge_duration_min != null
                        ? fmtDuration(row.avg_charge_duration_min)
                        : "—"}
                    </td>
                    <td className={tdNum}>
                      {row.energy_charged_kwh > 0
                        ? `${row.energy_charged_kwh} kWh`
                        : "—"}
                    </td>
                    <td className={tdNum}>
                      {row.avg_kwh_per_charge != null
                        ? `${row.avg_kwh_per_charge} kWh`
                        : "—"}
                    </td>
                    <td className={tdNum}>
                      {fmtCost(
                        row.total_cost,
                        row.currency_symbol,
                        row.currency_after
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
