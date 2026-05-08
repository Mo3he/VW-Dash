"use client";

interface Props {
  soc: number;
  rangeKm: number | null;
  targetSoc?: number | null;
}

export default function SocGauge({ soc, rangeKm, targetSoc }: Props) {
  const radius = 80;
  const stroke = 12;
  const normalizedRadius = radius - stroke / 2;
  const circumference = normalizedRadius * 2 * Math.PI;
  const half = circumference / 2; // we use a half-circle

  const color =
    soc >= 60 ? "#00B0F0" : soc >= 25 ? "#f59e0b" : "#ef4444";

  const filled = (soc / 100) * half;

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={radius * 2} height={radius + stroke} viewBox={`0 0 ${radius * 2} ${radius + stroke}`}>
        {/* Background arc */}
        <path
          d={`M ${stroke / 2} ${radius} A ${normalizedRadius} ${normalizedRadius} 0 0 1 ${radius * 2 - stroke / 2} ${radius}`}
          fill="none"
          stroke="#1e2535"
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
            {Math.round(rangeKm)} km estimated
          </div>
        )}
      </div>
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
