import type {
  BatteryHealth,
  ChargingSession,
  ChargingStats,
  Trip,
  TripStats,
  VehicleSnapshot,
} from "./types";

// Server components can't use relative URLs — they need to hit the backend directly.
// In the browser the Next.js dev-server proxy handles /api → backend.
const BASE =
  typeof window === "undefined"
    ? "http://localhost:8000/api"
    : "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  vehicle: {
    latest: () => get<VehicleSnapshot>("/vehicle/latest"),
    history: (hours = 24) =>
      get<VehicleSnapshot[]>(`/vehicle/history?hours=${hours}`),
    batteryHealth: () => get<BatteryHealth>("/vehicle/battery-health"),
  },
  charging: {
    sessions: (limit = 20, offset = 0) =>
      get<{ total: number; sessions: ChargingSession[] }>(
        `/charging/sessions?limit=${limit}&offset=${offset}`
      ),
    stats: (days = 30) => get<ChargingStats>(`/charging/stats?days=${days}`),
  },
  trips: {
    list: (limit = 20, offset = 0) =>
      get<{ total: number; trips: Trip[] }>(
        `/trips/?limit=${limit}&offset=${offset}`
      ),
    stats: (days = 30) => get<TripStats>(`/trips/stats?days=${days}`),
  },
};
