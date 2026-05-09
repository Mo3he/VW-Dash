"use client";
import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { ChargingSession, ChargingStats } from "@/lib/types";
import StatusCard from "@/components/StatusCard";
import ChargingSessionList from "./ChargingSessionList";

const PERIOD_OPTIONS = [
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "1y", days: 365 },
];
const PAGE_SIZE = 20;

export default function ChargingPage() {
  const [stats, setStats] = useState<ChargingStats | null>(null);
  const [sessions, setSessions] = useState<ChargingSession[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statsDays, setStatsDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const loadStats = useCallback(async () => {
    const s = await api.charging.stats(statsDays).catch(() => null);
    setStats(s);
  }, [statsDays]);

  const loadSessions = useCallback(async (off: number, append: boolean) => {
    const data = await api.charging.sessions(PAGE_SIZE, off).catch(() => ({ total: 0, sessions: [] as ChargingSession[] }));
    if (append) {
      setSessions((prev) => [...prev, ...data.sessions]);
    } else {
      setSessions(data.sessions);
    }
    setTotal(data.total);
    setOffset(off + data.sessions.length);
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadStats(), loadSessions(0, false)]).finally(() => setLoading(false));
  }, [loadStats, loadSessions]);

  async function handleLoadMore() {
    setLoadingMore(true);
    await loadSessions(offset, true);
    setLoadingMore(false);
  }

  function handleSessionUpdated(updated: ChargingSession) {
    setSessions((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
    loadStats();
  }

  const sym = stats?.currency_symbol ?? "$";
  const after = stats?.currency_after ?? false;
  const fmtCost = (n: number) =>
    after ? `${n.toFixed(2)} ${sym}` : `${sym}${n.toFixed(2)}`;

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-lg font-semibold text-white">Charging</h1>
        <div className="text-center text-gray-500 py-8">Loading…</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-white">Charging</h1>
        <div className="flex gap-1">
          {PERIOD_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              onClick={() => setStatsDays(opt.days)}
              className={`text-xs px-2.5 py-1 rounded-lg transition ${
                statsDays === opt.days
                  ? "bg-[#00B0F0]/20 text-[#00B0F0] font-medium"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {stats && (
        <div className="grid grid-cols-2 gap-3">
          <StatusCard
            label={`Sessions (${statsDays}d)`}
            value={stats.session_count}
          />
          <StatusCard
            label="Energy added"
            value={`${stats.total_kwh} kWh`}
            sub={`last ${statsDays} days`}
          />
          <StatusCard
            label="Estimated cost"
            value={fmtCost(stats.total_cost)}
            sub={`@ ${fmtCost(stats.electricity_rate)}/kWh`}
          />
          <StatusCard
            label="Range added"
            value={`${stats.total_range_km} km`}
            sub={`last ${statsDays} days`}
          />
          <StatusCard
            label="DC fast charges"
            value={stats.dc_session_count}
            sub={`last ${statsDays} days`}
          />
          <StatusCard
            label="Avg per session"
            value={`${stats.avg_kwh_per_session} kWh`}
          />
        </div>
      )}

      <ChargingSessionList
        sessions={sessions}
        total={total}
        onSessionUpdated={handleSessionUpdated}
      />

      {sessions.length < total && (
        <button
          onClick={handleLoadMore}
          disabled={loadingMore}
          className="w-full rounded-xl border border-white/10 py-2.5 text-sm text-gray-400
            hover:text-white hover:border-white/20 disabled:opacity-50 transition"
        >
          {loadingMore ? "Loading…" : `Load more (${total - sessions.length} remaining)`}
        </button>
      )}
    </div>
  );
}
