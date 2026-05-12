"use client";
import {
  ComposedChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from "recharts";
import type { RangeHealth } from "@/lib/types";
import { useTimezone, useDistanceUnit } from "@/app/SettingsProvider";
import { fmtDate } from "@/lib/format";

function stat(values: number[], fn: (a: number[]) => number) {
  const v = values.filter((x) => x != null && !isNaN(x));
  return v.length ? fn(v) : null;
}
const mean = (v: number[]) => v.reduce((a, b) => a + b, 0) / v.length;
const max = (v: number[]) => Math.max(...v);
const min = (v: number[]) => Math.min(...v);

export default function RangeHealthCard({ data }: { data: RangeHealth }) {
  const tz = useTimezone();
  const distanceUnit = useDistanceUnit();

  if (data.history.length === 0) {
    return (
      <div className="rounded-2xl bg-[var(--card-bg)] border border-white/5 p-4">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Consumption &amp; Range @ 100% SoC</div>
        <div className="text-xs text-gray-600 text-center py-4">No data in this period</div>
      </div>
    );
  }

  const toUnit = (km: number) => distanceUnit === "miles" ? Math.round(km * 0.621371) : Math.round(km);
  const unitLabel = distanceUnit === "miles" ? "mi" : "km";

  const points = data.history.map((h) => ({
    date: fmtDate(h.date, tz),
    range: toUnit(h.range_km),
    consumption: h.consumption_kwh_100km ?? undefined,
  }));

  const ratedInUnit = toUnit(data.rated_range_km);

  const rangeVals = points.map((p) => p.range);
  const consVals = points.map((p) => p.consumption).filter((x): x is number => x != null);
  const latest = points[points.length - 1];

  const statRows: { label: string; mean: string; last: string; maxV: string; minV: string; color: string }[] = [
    {
      label: `Range @ 100% SoC (${unitLabel})`,
      mean: stat(rangeVals, mean)?.toFixed(0) ?? "-",
      last: latest?.range?.toFixed(0) ?? "-",
      maxV: stat(rangeVals, max)?.toFixed(0) ?? "-",
      minV: stat(rangeVals, min)?.toFixed(0) ?? "-",
      color: "#4ade80",
    },
    {
      label: "Consumption (kWh/100km)",
      mean: stat(consVals, mean)?.toFixed(1) ?? "-",
      last: latest?.consumption?.toFixed(1) ?? "-",
      maxV: stat(consVals, max)?.toFixed(1) ?? "-",
      minV: stat(consVals, min)?.toFixed(1) ?? "-",
      color: "#facc15",
    },
  ];

  return (
    <div className="rounded-2xl bg-[var(--card-bg)] border border-white/5 p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs text-gray-500 uppercase tracking-wider">Consumption &amp; Range extrapolated to 100% SoC</span>
      </div>

      <div style={{ overflow: "visible" }}>
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart data={points} margin={{ top: 4, right: 0, left: -16, bottom: 0 }}>
          <XAxis
            dataKey="date"
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          {/* Left Y: range */}
          <YAxis
            yAxisId="range"
            orientation="left"
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            domain={["auto", "auto"]}
            tickFormatter={(v) => `${v}`}
            width={48}
          />
          {/* Right Y: consumption — negative right margin above cancels the axis width so lines reach the edge */}
          <YAxis
            yAxisId="cons"
            orientation="right"
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            domain={["auto", "auto"]}
            tickFormatter={(v) => `${v}`}
            width={32}
          />
          <ReferenceLine
            yAxisId="range"
            y={ratedInUnit}
            stroke="#22c55e"
            strokeDasharray="6 3"
            strokeWidth={1.5}
            label={{ value: `Rated ${ratedInUnit} ${unitLabel}`, position: "insideTopRight", fill: "#22c55e", fontSize: 10 }}
          />
          <Tooltip
            contentStyle={{ background: "#1e2535", border: "none", borderRadius: 8, fontSize: 12 }}
            formatter={(val: number, name: string) =>
              name === "range"
                ? [`${val} ${unitLabel}`, `Range @ 100%`]
                : [`${val} kWh/100km`, "Consumption"]
            }
          />
          <Line
            yAxisId="range"
            type="monotone"
            dataKey="range"
            stroke="#4ade80"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
          <Line
            yAxisId="cons"
            type="monotone"
            dataKey="consumption"
            stroke="#facc15"
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      </div>

      {/* Stats table */}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs text-gray-400">
          <thead>
            <tr className="text-[10px] text-gray-600 uppercase">
              <th className="text-left font-normal pb-1">Name</th>
              <th className="text-right font-normal pb-1">Mean</th>
              <th className="text-right font-normal pb-1">Last</th>
              <th className="text-right font-normal pb-1">Max</th>
              <th className="text-right font-normal pb-1">Min</th>
            </tr>
          </thead>
          <tbody>
            {statRows.map((r) => (
              <tr key={r.label}>
                <td className="py-0.5 flex items-center gap-1.5">
                  <span className="inline-block w-2.5 h-0.5 rounded" style={{ background: r.color }} />
                  {r.label}
                </td>
                <td className="text-right tabular-nums">{r.mean}</td>
                <td className="text-right tabular-nums">{r.last} *</td>
                <td className="text-right tabular-nums">{r.maxV}</td>
                <td className="text-right tabular-nums">{r.minV}</td>
              </tr>
            ))}
            <tr>
              <td className="py-0.5 flex items-center gap-1.5">
                <span className="inline-block w-2.5 h-0.5 rounded border-dashed" style={{ background: "#22c55e" }} />
                Rated range
              </td>
              <td className="text-right tabular-nums">{ratedInUnit}</td>
              <td className="text-right tabular-nums">{ratedInUnit} *</td>
              <td className="text-right tabular-nums">{ratedInUnit}</td>
              <td className="text-right tabular-nums">{ratedInUnit}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
