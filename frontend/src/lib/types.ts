export interface VehicleSnapshot {
  id: number;
  recorded_at: string;
  soc_pct: number | null;
  range_km: number | null;
  range_miles: number | null;
  charging_state: string | null;
  charge_power_kw: number | null;
  charge_rate_km_h: number | null;
  charge_type: string | null;
  remaining_charge_time_min: number | null;
  target_soc_pct: number | null;
  latitude: number | null;
  longitude: number | null;
  parking_time: string | null;
  outdoor_temp_c: number | null;
  cabin_temp_c: number | null;
  battery_temp_c: number | null;
  climatisation_state: string | null;
  locked: boolean | null;
  odometer_km: number | null;
  plug_connected: boolean | null;
  car_captured_at: string | null;
}

export interface ChargingSession {
  id: number;
  started_at: string;
  ended_at: string | null;
  duration_min: number | null;
  soc_start_pct: number | null;
  soc_end_pct: number | null;
  kwh_added: number | null;
  kwh_added_real: number | null;
  range_added_km: number | null;
  range_added_miles: number | null;
  peak_power_kw: number | null;
  avg_power_kw: number | null;
  charge_type: string | null;
  cost: number | null;
  cost_per_kwh: number | null;
  latitude: number | null;
  longitude: number | null;
  location_name: string | null;
  charger_id: number | null;
  currency_symbol: string;
  currency_after: boolean;
}

export interface Charger {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
}

export interface Trip {
  id: number;
  started_at: string;
  ended_at: string | null;
  duration_min: number | null;
  distance_km: number | null;
  distance_miles: number | null;
  soc_start_pct: number | null;
  soc_end_pct: number | null;
  kwh_used: number | null;
  efficiency_kwh_100km: number | null;
  avg_speed_kmh: number | null;
  start_lat: number | null;
  start_lon: number | null;
  end_lat: number | null;
  end_lon: number | null;
  outdoor_temp_c: number | null;
  outdoor_temp_f: number | null;
  start_address: string | null;
  end_address: string | null;
}

export interface ChargeLocation {
  name: string;
  latitude: number;
  longitude: number;
  sessions: number;
  total_kwh: number;
}

export interface TopCharger {
  name: string;
  sessions: number;
  total_kwh: number;
}

export interface ChargingStats {
  period_days: number;
  session_count: number;
  total_kwh: number;
  total_cost: number;
  total_range_km: number;
  dc_session_count: number;
  ac_session_count: number;
  avg_kwh_per_session: number;
  total_cycles: number;
  high_c_session_count: number;
  low_c_session_count: number;
  top_chargers: TopCharger[];
  est_vs_real_pct: number | null;
  electricity_rate: number;
  currency_symbol: string;
  currency_after: boolean;
  prev?: { session_count: number; total_kwh: number; total_cost: number };
}

export interface TripStats {
  period_days: number;
  trip_count: number;
  total_km: number;
  total_kwh: number;
  avg_efficiency_kwh_100km: number | null;
  cost_per_100km: number | null;
  currency_symbol: string;
  currency_after: boolean;
  temp_efficiency: Record<string, number>;
  prev?: { trip_count: number; total_km: number; total_kwh: number };
}

export interface RangeHealth {
  rated_range_km: number;
  history: { date: string; range_km: number }[];
}

export interface PopularRoute {
  start: string;
  end: string;
  count: number;
  avg_distance_km: number | null;
}

export interface Journey {
  date: string;
  trip_count: number;
  total_km: number;
  total_kwh: number;
  start_address: string | null;
  end_address: string | null;
  trips: Trip[];
}

export interface EventItem {
  id: number;
  occurred_at: string;
  event_type: string;
  label: string;
  detail: Record<string, unknown> | null;
}

export interface WsMessage {
  type: "snapshot";
  soc_pct: number | null;
  range_km: number | null;
  range_miles: number | null;
  charging_state: string | null;
  charge_power_kw: number | null;
  charge_rate_km_h: number | null;
  charge_type: string | null;
  remaining_charge_time_min: number | null;
  target_soc_pct: number | null;
  plug_connected: boolean | null;
  locked: boolean | null;
  outdoor_temp_c: number | null;
  battery_temp_c: number | null;
  cabin_temp_c: number | null;
  climatisation_state: string | null;
  recorded_at: string;
  car_captured_at: string | null;
}
