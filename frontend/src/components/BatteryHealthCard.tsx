"use client";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import type { RangeHealth } from "@/lib/types";
import { useTimezone } from "@/app/SettingsProvider";
import { fmtDate } from "@/lib/format";

export default function RangeHealthCard({ data }: { data: RangeHealth }) {
  const tz = useTimezone();

  if (data.history.length === 0) {
    return (
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Estimated range vs rated range</div>
        <div className="text-xs text-gray-600 text-center py-4">
          No data in this period — requires a snapshot at ≥99% SoC
        </div>
      </div>
    );
  }

  const points = data.history.map((h) => ({
    date: fmtDate(h.date, tz),
    range_km: Math.round(h.range_km),
  }));

  const latest = points[points.length - 1]?.range_km ?? null;
  const pct = latest != null ? Math.round((latest / data.rated_range_km) * 100) : null;

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-gray-500 uppercase tracking-wider">Estimated range vs rated range</div>
        {latest != null && (
          <span className="text-sm font-semibold text-[#00B0F0]">
            {latest} km{pct != null && <span className="text-gray-500 font-normal ml-1">({pct}%)</span>}
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={140}>
        <LineChart data={points} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <XAxis
            dataKey="date"
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            domain={["auto", "auto"]}
            tickFormatter={(v) => `${v}`}
          />
          <ReferenceLine
            y={data.rated_range_km}
            stroke="#6b7280"
            strokeDasharray="4 4"
            strokeWidth={1}
            label={{ value: `Rated ${data.rated_range_km} km`, position: "insideTopRight", fill: "#6b7280", fontSize: 10 }}
          />
          <Tooltip
            contentStyle={{ background: "#1e2535", border: "none", borderRadius: 8, fontSize: 12 }}
            formatter={(val: number) => [`${val} km`, "Observed range"]}
          />
          <Line
            type="monotone"
            dataKey="range_km"
            stroke="#00B0F0"
            strokeWidth={2}
            dot={{ r: 3, fill: "#00B0F0", strokeWidth: 0 }}
            activeDot={{ r: 5 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <div className="text-xs text-gray-600 mt-1 text-center">
        Observed range at ≥99% SoC — affected by temperature, terrain, and driving style
      </div>
    </div>
  );
}
