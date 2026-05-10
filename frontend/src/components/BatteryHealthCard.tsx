"use client";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import type { BatteryHealth } from "@/lib/types";
import { useTimezone } from "@/app/SettingsProvider";
import { fmtDate } from "@/lib/format";

function healthColor(pct: number): string {
  if (pct >= 90) return "text-green-400";
  if (pct >= 80) return "text-yellow-400";
  return "text-red-400";
}

export default function BatteryHealthCard({ data }: { data: BatteryHealth }) {
  const tz = useTimezone();

  if (data.latest_soh_pct == null && data.history.length === 0) {
    return (
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Battery health</div>
        <div className="text-xs text-gray-600 text-center py-4">
          No data yet — requires a snapshot at ≥99% SoC
        </div>
      </div>
    );
  }

  const points = data.history.map((h) => ({
    date: fmtDate(h.date, tz),
    soh: h.soh_pct,
  }));

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-gray-500 uppercase tracking-wider">Battery health</div>
        {data.latest_soh_pct != null && (
          <span className={`text-sm font-semibold ${healthColor(data.latest_soh_pct)}`}>
            {data.latest_soh_pct.toFixed(1)}%
          </span>
        )}
      </div>

      {points.length >= 2 ? (
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={points} margin={{ top: 4, right: 4, left: -28, bottom: 0 }}>
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
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              contentStyle={{ background: "#1e2535", border: "none", borderRadius: 8, fontSize: 12 }}
              formatter={(val: number) => [`${val.toFixed(1)}%`, "SoH"]}
            />
            <Line
              type="monotone"
              dataKey="soh"
              stroke="#4ade80"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="text-xs text-gray-600 text-center py-2">
          Need more readings at full charge to show trend
        </div>
      )}

      <div className="text-xs text-gray-600 mt-1 text-center">
        Based on observed range vs rated range at ≥99% SoC
      </div>
    </div>
  );
}
