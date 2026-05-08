import clsx from "clsx";

interface Props {
  label: string;
  value: React.ReactNode;
  sub?: string;
  accent?: boolean;
  className?: string;
}

export default function StatusCard({ label, value, sub, accent, className }: Props) {
  return (
    <div
      className={clsx(
        "rounded-2xl p-4 bg-[#161b27] border border-white/5",
        className
      )}
    >
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</div>
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
