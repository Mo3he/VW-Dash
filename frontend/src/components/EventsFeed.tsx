"use client";
import { useEffect, useRef, useState } from "react";
import {
  Car, Plug, Wind, Lock, Unlock, Zap, ZapOff, Navigation, NavigationOff,
} from "lucide-react";
import type { EventItem } from "@/lib/types";
import { api } from "@/lib/api";
import { useTimezone, useDistanceUnit } from "@/app/SettingsProvider";
import { fmtDate } from "@/lib/format";

const EVENT_CONFIG: Record<string, { icon: React.ReactNode; color: string }> = {
  trip_started:           { icon: <Navigation size={13} />,    color: "text-[#00B0F0]" },
  trip_ended:             { icon: <NavigationOff size={13} />, color: "text-gray-400" },
  charging_started:       { icon: <Zap size={13} />,           color: "text-yellow-400" },
  charging_ended:         { icon: <ZapOff size={13} />,        color: "text-gray-400" },
  connector_connected:    { icon: <Plug size={13} />,          color: "text-green-400" },
  connector_disconnected: { icon: <Plug size={13} />,          color: "text-gray-500" },
  climatisation_started:  { icon: <Wind size={13} />,          color: "text-cyan-400" },
  climatisation_stopped:  { icon: <Wind size={13} />,          color: "text-gray-500" },
  vehicle_locked:         { icon: <Lock size={13} />,          color: "text-green-400" },
  vehicle_unlocked:       { icon: <Unlock size={13} />,        color: "text-yellow-400" },
};

function timeAgo(iso: string, tz: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return fmtDate(iso, tz);
}

function eventSubtext(item: EventItem, distanceUnit: "km" | "miles"): string | null {
  const d = item.detail;
  if (!d) return null;
  if (item.event_type === "trip_ended" && d.distance_km != null) {
    const km = Number(d.distance_km);
    return distanceUnit === "miles"
      ? `${(km * 0.621371).toFixed(1)} mi`
      : `${km.toFixed(1)} km`;
  }
  if (item.event_type === "charging_ended" && d.kwh_added != null)
    return `${Number(d.kwh_added).toFixed(1)} kWh`;
  if ((item.event_type === "trip_started" || item.event_type === "charging_started") && d.soc_pct != null)
    return `SoC ${Math.round(Number(d.soc_pct))}%`;
  return null;
}

interface Props {
  /** Pass live?.recorded_at — component re-fetches (throttled) when this changes */
  pollTrigger?: string | null;
}

export default function EventsFeed({ pollTrigger }: Props) {
  const [events, setEvents] = useState<EventItem[]>([]);
  const tz = useTimezone();
  const distanceUnit = useDistanceUnit();
  const lastFetch = useRef(0);

  useEffect(() => {
    // Throttle re-fetches to at most once per 30s
    const now = Date.now();
    if (now - lastFetch.current < 30_000) return;
    lastFetch.current = now;
    api.events.list().then(setEvents).catch(() => {});
  }, [pollTrigger]);

  // Initial load
  useEffect(() => {
    api.events.list().then(setEvents).catch(() => {});
  }, []);

  if (!events.length) {
    return (
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Recent events</div>
        <div className="text-xs text-gray-600 text-center py-4">No events yet</div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Recent events</div>
      <div className="flex flex-col divide-y divide-white/5">
        {events.map((e) => {
          const cfg = EVENT_CONFIG[e.event_type] ?? {
            icon: <Car size={13} />,
            color: "text-gray-400",
          };
          const sub = eventSubtext(e, distanceUnit);
          return (
            <div key={e.id} className="flex items-center gap-3 py-2 first:pt-0 last:pb-0">
              <span className={`shrink-0 ${cfg.color}`}>{cfg.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="text-xs text-white leading-tight">{e.label}</div>
                {sub && <div className="text-xs text-gray-500 mt-0.5">{sub}</div>}
              </div>
              <div className="text-xs text-gray-600 shrink-0">{timeAgo(e.occurred_at, tz)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
