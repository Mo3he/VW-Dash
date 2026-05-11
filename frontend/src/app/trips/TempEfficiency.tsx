"use client";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { useTheme } from "@/components/ThemeProvider";

interface Props {
  data: Record<string, number>;
}

const COLORS: Record<string, string> = {
  "cold (<0°C)": "#60a5fa",
  "cool (0–10°C)": "#34d399",
  "mild (10–20°C)": "#fbbf24",
  "warm (>20°C)": "#f87171",
};

export default function TempEfficiency({ data }: Props) {
  const theme = useTheme();
  const isDark = theme === "dark";
  const tooltipStyle = {
    background: isDark ? "#1e2535" : "#ffffff",
    border: isDark ? "none" : "1px solid rgba(0,0,0,0.1)",
    borderRadius: 8,
    fontSize: 12,
    color: isDark ? undefined : "#111827",
  };
  const chartData = Object.entries(data).map(([label, value]) => ({
    label: label.split(" ")[0],
    fullLabel: label,
    value,
  }));

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">
        Efficiency by temperature (kWh/100km — lower is better)
      </div>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <XAxis
            dataKey="label"
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(val: number, _: string, props) => [
              `${val} kWh/100km`,
              props.payload.fullLabel,
            ]}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {chartData.map((entry) => (
              <Cell
                key={entry.label}
                fill={COLORS[entry.fullLabel] ?? "#00B0F0"}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
