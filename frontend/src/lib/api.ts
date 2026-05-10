import type {
  RangeHealth,
  ChargeLocation,
  ChargingSession,
  ChargingStats,
  EventItem,
  Journey,
  PopularRoute,
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

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  vehicle: {
    latest: () => get<VehicleSnapshot>("/vehicle/latest"),
    history: (hours = 24) =>
      get<VehicleSnapshot[]>(`/vehicle/history?hours=${hours}`),
    batteryHealth: (start?: string, end?: string) =>
      get<RangeHealth>(`/vehicle/battery-health${start ? `?start_date=${start}&end_date=${end}` : ""}`),
    climate: (action: "start" | "stop") =>
      post<{ status: string; action: string; target_state: string }>(
        `/vehicle/climate?action=${action}`
      ),
  },
  charging: {
    sessions: (limit = 20, offset = 0) =>
      get<{ total: number; sessions: ChargingSession[] }>(
        `/charging/sessions?limit=${limit}&offset=${offset}`
      ),
    stats: (start: string, end: string) =>
      get<ChargingStats>(`/charging/stats?start_date=${start}&end_date=${end}`),
    locations: () => get<ChargeLocation[]>(`/charging/locations`),
    updateSession: (id: number, body: Partial<ChargingSession>) =>
      patch<ChargingSession>(`/charging/sessions/${id}`, body),
  },
  trips: {
    list: (limit = 20, offset = 0, start?: string, end?: string) =>
      get<{ total: number; trips: Trip[] }>(
        `/trips?limit=${limit}&offset=${offset}${start ? `&start_date=${start}&end_date=${end}` : ""}`
      ),
    stats: (start: string, end: string) =>
      get<TripStats>(`/trips/stats?start_date=${start}&end_date=${end}`),
    route: (id: number) => get<{ trip_id: number; points: { lat: number; lon: number }[] }>(`/trips/${id}/route`),
    popular: (limit = 10) => get<PopularRoute[]>(`/trips/popular?limit=${limit}`),
    journeys: (start: string, end: string) =>
      get<Journey[]>(`/trips/journeys?start_date=${start}&end_date=${end}`),
  },
  events: {
    list: (limit = 50, days = 3) =>
      get<EventItem[]>(`/events?limit=${limit}&days=${days}`),
  },
};
