"use client";
import { useState, useEffect } from "react";
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
import { api } from "@/lib/api";
import { useTimezone, useHour12, useDistanceUnit } from "@/app/SettingsProvider";
import { fmtChartTime, fmtDate } from "@/lib/format";
import PeriodSelector, { DateRange, defaultRange } from "@/components/PeriodSelector";

interface Props {
  initialData: VehicleSnapshot[];
}

function downsample<T>(arr: T[], max: number): T[] {
  if (arr.length <= max) return arr;
  const step = arr.length / max;
  return Array.from({ length: max }, (_, i) => arr[Math.round(i * step)]);
}

function daysBetween(range: DateRange): number {
  const ms = new Date(range.end).getTime() - new Date(range.start).getTime();
  return ms / 86_400_000;
}

export default function SocHistory({ initialData }: Props) {
  const tz = useTimezone();
  const hour12 = useHour12();
  const distanceUnit = useDistanceUnit();
  const [range, setRange] = useState<DateRange>(defaultRange(1));
  const [data, setData] = useState<VehicleSnapshot[]>(initialData);

  useEffect(() => {
    api.vehicle.historyByRange(range.start, range.end).then(setData).catch(() => {});
  }, [range]);

  const sampled = downsample(data, 1000);
  const useTime = daysBetween(range) <= 2;

  const points = sampled.map((s) => ({
    label: useTime ? fmtChartTime(s.recorded_at, tz, hour12) : fmtDate(s.recorded_at, tz),
    soc: s.soc_pct,
    range_km: s.range_km != null
      ? distanceUnit === "miles"
        ? Math.round(s.range_km * 0.621371)
        : Math.round(s.range_km)
      : null,
  }));

  const hasRange = points.some((p) => p.range_km != null);

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="text-xs text-gray-500 uppercase tracking-wider">SoC history</div>
          {hasRange && (
            <div className="hidden sm:flex items-center gap-3 text-xs text-gray-500">
              <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-[#00B0F0]" /> SoC %</span>
              <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-[#34d399]" /> Range {distanceUnit === "miles" ? "mi" : "km"}</span>
            </div>
          )}
        </div>
        <PeriodSelector value={range} onChange={setRange} />
      </div>

      {points.length === 0 ? (
        <div className="h-40 flex items-center justify-center text-xs text-gray-600">No data for this period</div>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <ComposedChart data={points} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="socGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00B0F0" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#00B0F0" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="label"
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
              width={42}
            />
            {hasRange && (
              <YAxis
                yAxisId="range"
                orientation="right"
                domain={["auto", "auto"]}
                tick={{ fill: "#6b7280", fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                width={36}
              />
            )}
            <Tooltip
              contentStyle={{ background: "#1e2535", border: "none", borderRadius: 8, fontSize: 12 }}
              formatter={(val: number, key: string) =>
                key === "soc" ? [`${val}%`, "SoC"] : [`${val} ${distanceUnit === "miles" ? "mi" : "km"}`, "Range"]
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
                dataKey="range_km"
                stroke="#34d399"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
