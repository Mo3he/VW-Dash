"use client";
import { useDistanceUnit } from "@/app/SettingsProvider";
import { useAccentColor } from "@/components/ThemeProvider";

interface Props {
  soc: number;
  rangeKm: number | null;
  targetSoc?: number | null;
  /** When shown alongside charging gauges, display a label below to match them. */
  showLabel?: boolean;
}

export default function SocGauge({ soc, rangeKm, targetSoc, showLabel }: Props) {
  const distanceUnit = useDistanceUnit();
  const accent = useAccentColor();
  const radius = 80;
  const stroke = 12;
  const normalizedRadius = radius - stroke / 2;
  const circumference = normalizedRadius * 2 * Math.PI;
  const half = circumference / 2; // we use a half-circle

  const color =
    soc >= 60 ? accent : soc >= 25 ? "#f59e0b" : "#ef4444";

  const filled = (soc / 100) * half;

  return (
    <div className="flex flex-col items-center gap-2 min-w-0">
      <svg width="100%" viewBox={`0 0 ${radius * 2} ${radius + stroke}`} style={{ maxWidth: radius * 2, overflow: 'visible' }}>
        {/* Background arc */}
        <path
          d={`M ${stroke / 2} ${radius} A ${normalizedRadius} ${normalizedRadius} 0 0 1 ${radius * 2 - stroke / 2} ${radius}`}
          fill="none"
          style={{ stroke: "var(--soc-track)" }}
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Filled arc */}
        <path
          d={`M ${stroke / 2} ${radius} A ${normalizedRadius} ${normalizedRadius} 0 0 1 ${radius * 2 - stroke / 2} ${radius}`}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${half}`}
          style={{ transition: "stroke-dasharray 0.8s ease" }}
        />
        {/* Target SoC tick */}
        {targetSoc != null && (
          <TargetTick
            targetSoc={targetSoc}
            radius={normalizedRadius}
            cx={radius}
            cy={radius}
          />
        )}
      </svg>
      <div className="text-center -mt-4">
        <div className="text-5xl font-bold tabular-nums" style={{ color }}>
          {Math.round(soc)}
          <span className="text-2xl font-normal text-gray-400">%</span>
        </div>
        {rangeKm != null && (
          <div className="text-gray-400 text-sm mt-1">
            {distanceUnit === "miles"
              ? `${Math.round(rangeKm * 0.621371)} mi`
              : `${Math.round(rangeKm)} km`} estimated
          </div>
        )}
      </div>
      {showLabel && (
        <div className="text-xs text-gray-500 uppercase tracking-wider">Battery</div>
      )}
    </div>
  );
}

function TargetTick({
  targetSoc,
  radius,
  cx,
  cy,
}: {
  targetSoc: number;
  radius: number;
  cx: number;
  cy: number;
}) {
  const angle = Math.PI - (targetSoc / 100) * Math.PI;
  const x = cx + radius * Math.cos(angle);
  const y = cy - radius * Math.sin(angle);
  return (
    <circle cx={x} cy={y} r={5} fill="#f59e0b" opacity={0.8} />
  );
}
