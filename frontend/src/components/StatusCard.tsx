import clsx from "clsx";

interface Props {
  label: string;
  value: React.ReactNode;
  sub?: string;
  accent?: boolean;
  className?: string;
  /** Percentage or absolute delta vs previous period (positive = up, negative = down) */
  delta?: number | null;
  /** If true, higher delta is bad (e.g. energy consumed) */
  deltaInvert?: boolean;
}

export default function StatusCard({ label, value, sub, accent, className, delta, deltaInvert }: Props) {
  const hasDelta = delta != null && !isNaN(delta) && isFinite(delta);
  const isPositive = delta != null && delta > 0;
  const good = deltaInvert ? !isPositive : isPositive;

  return (
    <div
      className={clsx(
        "rounded-2xl p-4 bg-[#161b27] border border-white/5",
        className
      )}
    >
      <div className="flex items-start justify-between mb-1">
        <div className="text-xs text-gray-500 uppercase tracking-wider">{label}</div>
        {hasDelta && delta !== 0 && (
          <span
            className={clsx(
              "text-[10px] px-1.5 py-0.5 rounded-full font-medium leading-none",
              good ? "text-green-400 bg-green-400/10" : "text-red-400 bg-red-400/10"
            )}
          >
            {isPositive ? "▲" : "▼"} {Math.abs(delta).toFixed(0)}%
          </span>
        )}
      </div>
      <div
        className={clsx(
          "text-xl font-semibold",
          accent ? "text-[#00B0F0]" : "text-white"
        )}
      >
        {value}
      </div>
      {sub && <div className="text-xs text-gray-500 mt-0.5">{sub}</div>}
    </div>
  );
}
