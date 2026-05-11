"use client";
import { useEffect, useState } from "react";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";
import { authHeaders } from "@/lib/auth";

import { useTheme, useAccentColor } from "@/components/ThemeProvider";

interface CurvePoint {
  t: string;
  kw: number | null;
  soc: number | null;
}

interface Props {
  sessionId: number;
}

export default function ChargingCurve({ sessionId }: Props) {
  const [points, setPoints] = useState<CurvePoint[]>([]);
  const [loading, setLoading] = useState(true);
  const theme = useTheme();
  const isDark = theme === "dark";
  const accent = useAccentColor();
  const tooltipStyle = {
    background: isDark ? "#1a1f2e" : "#ffffff",
    border: isDark ? "1px solid rgba(255,255,255,0.1)" : "1px solid rgba(0,0,0,0.1)",
    borderRadius: 8,
    fontSize: 11,
    color: isDark ? undefined : "#111827",
  };
  const gridStroke = isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.06)";

  useEffect(() => {
    setLoading(true);
    fetch(`/api/charging/sessions/${sessionId}/curve`, { headers: authHeaders() })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setPoints(d.points ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) return <div className="h-24 flex items-center justify-center text-xs text-gray-600">Loading curve…</div>;
  if (!points.length) return <div className="h-24 flex items-center justify-center text-xs text-gray-600">No power readings recorded</div>;

  const data = points.map((p, i) => ({
    i,
    kw: p.kw ?? 0,
    soc: p.soc,
    t: p.t,
  }));

  return (
    <div className="mt-3">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Charge curve</div>
      <ResponsiveContainer width="100%" height={100}>
        <AreaChart data={data} margin={{ top: 4, right: 0, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id={`cc-${sessionId}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={accent} stopOpacity={0.3} />
              <stop offset="95%" stopColor={accent} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
          <XAxis dataKey="i" hide />
          <YAxis tick={{ fontSize: 9, fill: "#6b7280" }} domain={[0, "dataMax + 5"]} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={() => ""}
            formatter={(val: number, name: string) =>
              name === "kw" ? [`${val.toFixed(1)} kW`, "Power"] : [`${val}%`, "SoC"]
            }
          />
          <Area
            type="monotone"
            dataKey="kw"
            stroke={accent}
            strokeWidth={1.5}
            fill={`url(#cc-${sessionId})`}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
