"use client";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { Trip } from "@/lib/types";

interface Props {
  trips: Trip[];
}

function downsample<T>(arr: T[], max: number): T[] {
  if (arr.length <= max) return arr;
  const step = arr.length / max;
  return Array.from({ length: max }, (_, i) => arr[Math.round(i * step)]);
}

export default function EfficiencyChart({ trips }: Props) {
  const filtered = [...trips]
    .filter((t) => t.efficiency_kwh_100km != null && t.distance_km != null && t.distance_km > 0.5)
    .reverse(); // chronological order

  if (filtered.length < 2) return null;

  // Downsample to ≤100 points spread evenly across the full period
  const ordered = downsample(filtered, 100);

  const points = ordered.map((t) => ({
    date: new Date(t.started_at).toLocaleDateString([], { month: "short", day: "numeric" }),
    efficiency: t.efficiency_kwh_100km,
    distance: t.distance_km,
  }));

  const avg =
    points.reduce((sum, p) => sum + (p.efficiency ?? 0), 0) / points.length;

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-gray-500 uppercase tracking-wider">
          Efficiency per trip (kWh/100km)
        </div>
        <div className="text-xs text-gray-500">
          avg {avg.toFixed(1)}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <AreaChart data={points} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="effGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#34d399" stopOpacity={0.25} />
              <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
            </linearGradient>
          </defs>
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
          />
          <ReferenceLine
            y={avg}
            stroke="#6b7280"
            strokeDasharray="3 3"
            strokeWidth={1}
          />
          <Tooltip
            contentStyle={{
              background: "#1e2535",
              border: "none",
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(val: number, _: string, props) => [
              `${val} kWh/100km`,
              `${props.payload.distance?.toFixed(1)} km`,
            ]}
          />
          <Area
            type="monotone"
            dataKey="efficiency"
            stroke="#34d399"
            strokeWidth={2}
            fill="url(#effGrad)"
            dot={{ r: 3, fill: "#34d399", strokeWidth: 0 }}
            activeDot={{ r: 5 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
      <div className="text-xs text-gray-600 mt-1 text-center">lower is better</div>
    </div>
  );
}
