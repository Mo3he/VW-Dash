"use client";
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { VehicleSnapshot } from "@/lib/types";
import { useTimezone } from "@/app/SettingsProvider";
import { fmtChartTime } from "@/lib/format";

interface Props {
  data: VehicleSnapshot[];
}

export default function SocHistory({ data }: Props) {
  const tz = useTimezone();
  const points = data.map((s) => ({
    time: fmtChartTime(s.recorded_at, tz),
    soc: s.soc_pct,
    range: s.range_km != null ? Math.round(s.range_km) : null,
  }));

  const hasRange = points.some((p) => p.range != null);

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-gray-500 uppercase tracking-wider">SoC — last 24h</div>
        {hasRange && (
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-[#00B0F0]" /> SoC %</span>
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-[#34d399]" /> Range km</span>
          </div>
        )}
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <ComposedChart data={points} margin={{ top: 4, right: hasRange ? 4 : 4, left: -20, bottom: 0 }}>
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
            yAxisId="soc"
            domain={[0, 100]}
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}%`}
            width={36}
          />
          {hasRange && (
            <YAxis
              yAxisId="range"
              orientation="right"
              domain={["auto", "auto"]}
              tick={{ fill: "#6b7280", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `${v}`}
              width={36}
            />
          )}
          <Tooltip
            contentStyle={{ background: "#1e2535", border: "none", borderRadius: 8, fontSize: 12 }}
            formatter={(val: number, key: string) =>
              key === "soc" ? [`${val}%`, "SoC"] : [`${val} km`, "Range"]
            }
          />
          <Area
            yAxisId="soc"
            type="monotone"
            dataKey="soc"
            stroke="#00B0F0"
            strokeWidth={2}
            fill="url(#socGrad)"
            dot={false}
            isAnimationActive={false}
          />
          {hasRange && (
            <Line
              yAxisId="range"
              type="monotone"
              dataKey="range"
              stroke="#34d399"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
