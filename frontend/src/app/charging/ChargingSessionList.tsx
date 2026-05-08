"use client";
import { Zap } from "lucide-react";
import type { ChargingSession } from "@/lib/types";
import clsx from "clsx";

interface Props {
  sessions: ChargingSession[];
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ChargingSessionList({ sessions }: Props) {
  if (!sessions.length) {
    return (
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-6 text-center text-gray-500">
        No charging sessions recorded yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-gray-500 uppercase tracking-wider px-1">Recent sessions</div>
      {sessions.map((s) => (
        <div
          key={s.id}
          className="rounded-2xl bg-[#161b27] border border-white/5 p-4"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm text-white font-medium">{formatDate(s.started_at)}</div>
            <span
              className={clsx(
                "text-xs px-2 py-0.5 rounded-full font-medium",
                s.charge_type === "DC"
                  ? "bg-yellow-400/10 text-yellow-400"
                  : "bg-[#00B0F0]/10 text-[#00B0F0]"
              )}
            >
              {s.charge_type ?? "AC"}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <div className="text-lg font-semibold text-white">
                {s.soc_start_pct != null ? `${Math.round(s.soc_start_pct)}%` : "—"}
                <span className="text-gray-500 mx-1">→</span>
                {s.soc_end_pct != null ? `${Math.round(s.soc_end_pct)}%` : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">SoC</div>
            </div>
            <div>
              <div className="text-lg font-semibold text-[#00B0F0] flex items-center justify-center gap-1">
                <Zap size={14} />
                {s.kwh_added != null ? `${s.kwh_added}` : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">kWh</div>
            </div>
            <div>
              <div className="text-lg font-semibold text-white">
                {s.cost != null
                  ? s.currency_after
                    ? `${s.cost.toFixed(2)} ${s.currency_symbol}`
                    : `${s.currency_symbol}${s.cost.toFixed(2)}`
                  : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">Cost</div>
            </div>
          </div>
          {s.duration_min != null && (
            <div className="text-xs text-gray-600 mt-2 text-right">
              {s.duration_min} min
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
