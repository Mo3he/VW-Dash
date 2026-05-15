import type {
  Charger,
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
  MonthlyStats,
} from "./types";

import { authHeaders } from "./auth";

// Server components can't use relative URLs — they need to hit the backend directly.
// In the browser the Next.js dev-server proxy handles /api → backend.
const BASE =
  typeof window === "undefined"
    ? "http://localhost:8000/api"
    : "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...authHeaders(),
    },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: "DELETE",
    headers: authHeaders(),
    cache: "no-store",
  });
  if (!res.ok && res.status !== 204) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
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
  auth: {
    needsSetup: () => get<{ needs_setup: boolean }>("/auth/setup"),
    login: (username: string, password: string) =>
      post<{ access_token: string; username: string; is_admin: boolean }>("/auth/login", { username, password }),
    me: () => get<{ id: number; username: string; is_admin: boolean }>("/auth/me"),
    users: () => get<{ id: number; username: string; is_admin: boolean; created_at: string }[]>("/auth/users"),
    createUser: (username: string, password: string, is_admin: boolean) =>
      post<{ id: number; username: string; is_admin: boolean; created_at: string }>("/auth/users", { username, password, is_admin }),
    deleteUser: (id: number) => del(`/auth/users/${id}`),
    changePassword: (id: number, password: string) =>
      post<{ ok: boolean }>(`/auth/users/${id}/password`, { password }),
  },
  vehicle: {
    latest: () => get<VehicleSnapshot>("/vehicle/latest"),
    history: (hours = 24) =>
      get<VehicleSnapshot[]>(`/vehicle/history?hours=${hours}`),
    historyByRange: (start: string, end: string) =>
      get<VehicleSnapshot[]>(`/vehicle/history?start_date=${start}&end_date=${end}`),
    batteryHealth: (start?: string, end?: string) =>
      get<RangeHealth>(`/vehicle/battery-health${start ? `?start_date=${start}&end_date=${end}` : ""}`),
    vampireDrain: (days = 30) => get<{ avg_drain_pct_per_h: number | null; total_soc_lost: number | null; events: unknown[] }>(`/vehicle/vampire-drain?days=${days}`),
    climate: (action: "start" | "stop") =>
      post<{ status: string; action: string; target_state: string }>(
        `/vehicle/climate?action=${action}`
      ),
    chargingControl: (action: "start" | "stop") =>
      post<{ status: string; action: string }>(
        `/vehicle/charging-control?action=${action}`
      ),
    poll: () => post<{ status: string }>("/vehicle/poll"),
  },
  charging: {
    sessions: (limit = 20, offset = 0) =>
      get<{ total: number; sessions: ChargingSession[] }>(
        `/charging/sessions?limit=${limit}&offset=${offset}`
      ),
    stats: (start: string, end: string) =>
      get<ChargingStats>(`/charging/stats?start_date=${start}&end_date=${end}`),
    locations: (start?: string, end?: string) =>
      get<ChargeLocation[]>(`/charging/locations${start ? `?start_date=${start}&end_date=${end}` : ""}`),
    updateSession: (id: number, body: Partial<ChargingSession>) =>
      patch<ChargingSession>(`/charging/sessions/${id}`, body),
    deleteSession: (id: number) => del(`/charging/sessions/${id}`),
    createSession: (body: {
      started_at: string; ended_at: string;
      soc_start_pct?: number; soc_end_pct?: number;
      kwh_added?: number; charge_type?: string; location_name?: string;
      charger_id?: number; latitude?: number; longitude?: number;
    }) => post<ChargingSession>("/charging/sessions", body),
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
    delete: (id: number) => del(`/trips/${id}`),
    update: (id: number, body: { start_address?: string | null; end_address?: string | null; distance_km?: number; soc_start_pct?: number; soc_end_pct?: number; odometer_start_km?: number; odometer_end_km?: number }) =>
      patch<Trip>(`/trips/${id}`, body),
    create: (body: {
      started_at: string; ended_at: string; distance_km: number;
      soc_start_pct?: number; soc_end_pct?: number;
      start_address?: string; end_address?: string;
    }) => post<Trip>("/trips", body),
  },
  chargers: {
    list: () => get<Charger[]>("/chargers"),
    create: (body: { name: string; latitude: number; longitude: number }) =>
      post<Charger>("/chargers", body),
    update: (id: number, body: { name?: string; latitude?: number; longitude?: number }) =>
      patch<Charger>(`/chargers/${id}`, body),
    delete: (id: number) => del(`/chargers/${id}`),
  },
  events: {
    list: (limit = 50, days = 3) =>
      get<EventItem[]>(`/events?limit=${limit}&days=${days}`),
  },
  stats: {
    monthly: () => get<MonthlyStats[]>("/stats/monthly"),
  },
  geocoder: {
    search: (q: string) =>
      get<{ display_name: string; lat: number; lon: number }[]>(
        `/geocoder/search?q=${encodeURIComponent(q)}`
      ),
  },
};
