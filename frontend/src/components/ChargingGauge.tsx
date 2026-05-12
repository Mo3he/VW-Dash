"use client";
import { useAccentColor } from "@/components/ThemeProvider";

interface Props {
  /** Value displayed large in the centre of the arc. */
  value: string;
  /** Smaller line below the value (e.g. finish time or rate). */
  sub?: string | null;
  /** Label beneath the gauge. */
  label: string;
  /** 0–1 fill fraction for the arc. */
  fill: number;
  /** Override arc colour. Defaults to accent. */
  color?: string;
}

export default function ChargingGauge({ value, sub, label, fill, color }: Props) {
  const accent = useAccentColor();
  const arcColor = color ?? accent;
  const radius = 56;
  const stroke = 9;
  const nr = radius - stroke / 2;
  const circumference = nr * Math.PI; // half-circle arc length
  const filled = Math.max(0, Math.min(1, fill)) * circumference;
  const w = radius * 2;
  const h = radius + stroke;

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
        {/* Track */}
        <path
          d={`M ${stroke / 2} ${radius} A ${nr} ${nr} 0 0 1 ${w - stroke / 2} ${radius}`}
          fill="none"
          style={{ stroke: "var(--soc-track)" }}
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Fill */}
        <path
          d={`M ${stroke / 2} ${radius} A ${nr} ${nr} 0 0 1 ${w - stroke / 2} ${radius}`}
          fill="none"
          stroke={arcColor}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          style={{ transition: "stroke-dasharray 0.8s ease" }}
        />
      </svg>
      <div className="text-center -mt-3">
        <div className="text-xl font-bold tabular-nums text-white leading-tight">{value}</div>
        {sub && <div className="text-xs text-gray-500 mt-0.5 leading-tight">{sub}</div>}
      </div>
      <div className="text-xs text-gray-500 uppercase tracking-wider">{label}</div>
    </div>
  );
}
