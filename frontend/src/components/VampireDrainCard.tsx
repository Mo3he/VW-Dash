"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface DrainData {
  avg_drain_pct_per_h: number | null;
  total_soc_lost: number | null;
  events: unknown[];
}

export default function VampireDrainCard() {
  const [data, setData] = useState<DrainData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.vehicle.vampireDrain(30).then(setData).catch((e: Error) => setError(e.message));
  }, []);

  if (error) return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Vampire drain</div>
      <div className="text-xs text-red-400">{error}</div>
    </div>
  );

  if (!data || data.avg_drain_pct_per_h == null) return null;

  const drainPerDay = data.avg_drain_pct_per_h * 24;

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Vampire drain (30d)</div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className="text-lg font-semibold text-white">
            {data.avg_drain_pct_per_h.toFixed(2)}%
          </div>
          <div className="text-xs text-gray-500 mt-0.5">per hour</div>
        </div>
        <div>
          <div className="text-lg font-semibold text-white">
            {drainPerDay.toFixed(1)}%
          </div>
          <div className="text-xs text-gray-500 mt-0.5">per day</div>
        </div>
        <div>
          <div className="text-lg font-semibold text-white">
            {data.total_soc_lost?.toFixed(0) ?? "—"}%
          </div>
          <div className="text-xs text-gray-500 mt-0.5">total lost</div>
        </div>
      </div>
    </div>
  );
}
