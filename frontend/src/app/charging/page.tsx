"use client";
import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { ChargingSession, ChargingStats } from "@/lib/types";
import StatusCard from "@/components/StatusCard";
import ChargeMap from "@/components/ChargeMap";
import ChargingSessionList from "./ChargingSessionList";
import PeriodSelector from "@/components/PeriodSelector";

function periodLabel(days: number) {
  return days >= 3650 ? "all time" : `last ${days} days`;
}
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
        <PeriodSelector value={statsDays} onChange={setStatsDays} />
      </div>

      {stats && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <StatusCard
              label={`Sessions (${periodLabel(statsDays)})`}
              value={stats.session_count}
            />
            <StatusCard
              label="Battery cycles"
              value={stats.total_cycles}
              sub={periodLabel(statsDays)}
            />
            <StatusCard
              label="Energy added"
              value={`${stats.total_kwh} kWh`}
              sub={`avg ${stats.avg_kwh_per_session} kWh/session`}
            />
            <StatusCard
              label="Estimated cost"
              value={fmtCost(stats.total_cost)}
              sub={`@ ${fmtCost(stats.electricity_rate)}/kWh`}
            />
            <StatusCard
              label="Range added"
              value={`${stats.total_range_km} km`}
            />
            <StatusCard
              label="AC / DC"
              value={`${stats.ac_session_count} / ${stats.dc_session_count}`}
              sub="sessions"
            />
            {stats.est_vs_real_pct != null && (
              <StatusCard
                label="Est. vs real"
                value={`${stats.est_vs_real_pct > 0 ? "+" : ""}${stats.est_vs_real_pct}%`}
                sub="avg accuracy"
              />
            )}
          </div>

          {/* Top chargers */}
          {stats.top_chargers.length > 0 && (
            <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
              <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">
                Top chargers
              </div>
              <div className="flex flex-col divide-y divide-white/5">
                {stats.top_chargers.map((c, i) => (
                  <div key={c.name} className="flex items-center gap-3 py-2 first:pt-0 last:pb-0">
                    <span className="text-xs text-gray-600 w-4 shrink-0">{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-white truncate">{c.name}</div>
                      <div className="text-xs text-gray-500 mt-0.5">{c.sessions} sessions</div>
                    </div>
                    <div className="text-xs text-[#00B0F0] shrink-0">{c.total_kwh} kWh</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      <ChargeMap />

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
