"use client";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { VehicleSnapshot } from "@/lib/types";

interface Props {
  data: VehicleSnapshot[];
}

export default function SocHistory({ data }: Props) {
  const points = data.map((s) => ({
    time: new Date(s.recorded_at).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
    soc: s.soc_pct,
  }));

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">
        SoC — last 24h
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <AreaChart data={points} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="socGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#00B0F0" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#00B0F0" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="time"
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              background: "#1e2535",
              border: "none",
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(val: number) => [`${val}%`, "SoC"]}
          />
          <Area
            type="monotone"
            dataKey="soc"
            stroke="#00B0F0"
            strokeWidth={2}
            fill="url(#socGrad)"
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
