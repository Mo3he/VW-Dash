"use client";
import { useState } from "react";
import type { Trip } from "@/lib/types";
import { Zap, Gauge, MapPin, ChevronDown, Trash2, Pencil, X, Check } from "lucide-react";
import clsx from "clsx";
import TripMap from "@/components/TripMap";
import { api } from "@/lib/api";
import { useTimezone, useHour12, useDistanceUnit } from "@/app/SettingsProvider";
import { fmtDateTime, fmtDist } from "@/lib/format";
import LocationSearch from "@/components/LocationSearch";

interface Props {
  trips: Trip[];
  total: number;
  onDelete?: (id: number) => void;
  onUpdate?: (updated: Trip) => void;
}

interface EditState {
  start_address: string;
  end_address: string;
  distance_km: string;
  soc_start_pct: string;
  soc_end_pct: string;
  odometer_start_km: string;
  odometer_end_km: string;
}

function formatDuration(min: number | null) {
  if (min == null) return null;
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function efficiencyColor(kwh: number | null): string {
  if (kwh == null) return "text-white";
  if (kwh < 16) return "text-green-400";
  if (kwh < 20) return "text-[#00B0F0]";
  if (kwh < 25) return "text-yellow-400";
  return "text-red-400";
}

type RouteCache = Record<number, { lat: number; lon: number }[]>;

export default function TripList({ trips, total, onDelete, onUpdate }: Props) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [routeCache, setRouteCache] = useState<RouteCache>({});
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const tz = useTimezone();
  const hour12 = useHour12();
  const distanceUnit = useDistanceUnit();

  function startEdit(e: React.MouseEvent, t: Trip) {
    e.stopPropagation();
    setEditingId(t.id);
    setEditState({
      start_address: t.start_address ?? "",
      end_address: t.end_address ?? "",
      distance_km: t.distance_km?.toString() ?? "",
      soc_start_pct: t.soc_start_pct?.toString() ?? "",
      soc_end_pct: t.soc_end_pct?.toString() ?? "",
      odometer_start_km: t.odometer_start_km?.toString() ?? "",
      odometer_end_km: t.odometer_end_km?.toString() ?? "",
    });
    setSaveError(null);
  }

  function cancelEdit(e: React.MouseEvent) {
    e.stopPropagation();
    setEditingId(null);
    setEditState(null);
    setSaveError(null);
  }

  async function saveEdit(e: React.MouseEvent, t: Trip) {
    e.stopPropagation();
    if (!editState) return;
    setSaving(true);
    setSaveError(null);
    try {
      const body: Parameters<typeof api.trips.update>[1] = {};
      // Always send addresses so they can be cleared
      body.start_address = editState.start_address.trim() || null;
      body.end_address = editState.end_address.trim() || null;
      if (editState.distance_km) body.distance_km = parseFloat(editState.distance_km);
      if (editState.soc_start_pct) body.soc_start_pct = parseFloat(editState.soc_start_pct);
      if (editState.soc_end_pct) body.soc_end_pct = parseFloat(editState.soc_end_pct);
      if (editState.odometer_start_km) body.odometer_start_km = parseFloat(editState.odometer_start_km);
      if (editState.odometer_end_km) body.odometer_end_km = parseFloat(editState.odometer_end_km);
      const updated = await api.trips.update(t.id, body);
      onUpdate?.(updated);
      setEditingId(null);
      setEditState(null);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(e: React.MouseEvent, id: number) {
    e.stopPropagation();
    if (!confirm("Delete this trip?")) return;
    setDeletingId(id);
    try {
      await api.trips.delete(id);
      onDelete?.(id);
    } catch {
      // ignore
    } finally {
      setDeletingId(null);
    }
  }

  async function toggleTrip(id: number) {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!routeCache[id]) {
      const data = await api.trips.route(id).catch(() => null);
      if (data) setRouteCache((prev) => ({ ...prev, [id]: data.points }));
    }
  }

  if (!trips.length) {
    return (
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-6 text-center text-gray-500">
        No trips recorded yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-gray-500 uppercase tracking-wider px-1">
        All trips ({total})
      </div>
      {trips.map((t) => (
        <div
          key={t.id}
          className="rounded-2xl bg-[#161b27] border border-white/5 p-4 cursor-pointer"
          onClick={() => editingId !== t.id && toggleTrip(t.id)}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm text-white font-medium">{fmtDateTime(t.started_at, tz, hour12)}</div>
            <div className="flex items-center gap-1">
              {editingId === t.id ? (
                <>
                  <button
                    type="button"
                    onClick={(e) => saveEdit(e, t)}
                    disabled={saving}
                    className="p-1 text-[#00B0F0] hover:text-white transition-colors disabled:opacity-40"
                    title="Save"
                  >
                    <Check size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={cancelEdit}
                    className="p-1 text-gray-500 hover:text-white transition-colors"
                    title="Cancel"
                  >
                    <X size={14} />
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={(e) => startEdit(e, t)}
                  className="p-1 text-gray-600 hover:text-gray-300 transition-colors"
                  title="Edit trip"
                >
                  <Pencil size={14} />
                </button>
              )}
              {onDelete && (
                <button
                  type="button"
                  onClick={(e) => handleDelete(e, t.id)}
                  disabled={deletingId === t.id}
                  className="p-1 text-gray-600 hover:text-red-400 transition-colors disabled:opacity-40"
                  title="Delete trip"
                >
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          </div>

          {editingId === t.id && editState ? (
            <div className="flex flex-col gap-2 mt-1 mb-3" onClick={(e) => e.stopPropagation()}>
              <div>
                <span className="text-xs text-gray-500 block mb-1">Start location</span>
                <LocationSearch
                  value={editState.start_address}
                  placeholder="Search start address…"
                  onSelect={(name) => setEditState({ ...editState, start_address: name })}
                  className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white w-full"
                />
              </div>
              <div>
                <span className="text-xs text-gray-500 block mb-1">End location</span>
                <LocationSearch
                  value={editState.end_address}
                  placeholder="Search end address…"
                  onSelect={(name) => setEditState({ ...editState, end_address: name })}
                  className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white w-full"
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <span className="text-xs text-gray-500 block mb-1">Distance (km)</span>
                  <input
                    type="number"
                    min="0.1"
                    step="0.1"
                    value={editState.distance_km}
                    onChange={(e) => setEditState({ ...editState, distance_km: e.target.value })}
                    className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white w-full"
                  />
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-1">SoC start %</span>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={editState.soc_start_pct}
                    onChange={(e) => setEditState({ ...editState, soc_start_pct: e.target.value })}
                    className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white w-full"
                  />
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-1">SoC end %</span>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={editState.soc_end_pct}
                    onChange={(e) => setEditState({ ...editState, soc_end_pct: e.target.value })}
                    className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white w-full"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <span className="text-xs text-gray-500 block mb-1">Odo start (km)</span>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={editState.odometer_start_km}
                    onChange={(e) => setEditState({ ...editState, odometer_start_km: e.target.value })}
                    className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white w-full"
                  />
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-1">Odo end (km)</span>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={editState.odometer_end_km}
                    onChange={(e) => setEditState({ ...editState, odometer_end_km: e.target.value })}
                    className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white w-full"
                  />
                </div>
              </div>
              {saveError && <div className="text-xs text-red-400">{saveError}</div>}
            </div>
          ) : (
            <>
              {/* Location row */}
              {(t.start_address || t.end_address) && (
                <div className="flex items-start gap-1.5 mb-3 text-xs text-gray-400">
                  <MapPin size={12} className="text-[#00B0F0] mt-0.5 shrink-0" />
                  <span className="truncate">
                    {t.start_address ?? "Unknown"}
                    <span className="text-gray-600 mx-1">→</span>
                    {t.end_address ?? "Unknown"}
                  </span>
                </div>
              )}

          {/* Primary metrics row */}
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <div className="text-lg font-semibold text-white">
                {distanceUnit === "miles"
                  ? (t.distance_miles != null ? t.distance_miles.toFixed(1) : t.distance_km != null ? (t.distance_km * 0.621371).toFixed(1) : "—")
                  : (t.distance_km != null ? t.distance_km.toFixed(1) : "—")}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">{distanceUnit === "miles" ? "mi" : "km"}</div>
            </div>
            <div>
              <div className="text-lg font-semibold text-white">
                {t.soc_start_pct != null ? `${Math.round(t.soc_start_pct)}%` : "—"}
                <span className="text-gray-500 mx-1">→</span>
                {t.soc_end_pct != null ? `${Math.round(t.soc_end_pct)}%` : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">SoC</div>
            </div>
            <div>
              <div className={clsx("text-lg font-semibold", efficiencyColor(t.efficiency_kwh_100km))}>
                {t.efficiency_kwh_100km != null
                  ? distanceUnit === "miles"
                    ? (t.efficiency_kwh_100km * 1.60934).toFixed(1)
                    : t.efficiency_kwh_100km
                  : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">{distanceUnit === "miles" ? "kWh/100mi" : "kWh/100km"}</div>
            </div>
          </div>

          {/* Secondary metrics row */}
          <div className="grid grid-cols-2 gap-3 text-center mt-3">
            <div>
              <div className="flex items-center justify-center gap-1 text-sm font-medium text-white">
                <Zap size={13} className="text-yellow-400" />
                {t.kwh_used != null ? `${t.kwh_used} kWh` : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">Energy used</div>
            </div>
            <div>
              <div className="flex items-center justify-center gap-1 text-sm font-medium text-white">
                <Gauge size={13} className="text-gray-400" />
                {t.avg_speed_kmh != null
                  ? distanceUnit === "miles"
                    ? `${Math.round(t.avg_speed_kmh * 0.621371)} mph`
                    : `${Math.round(t.avg_speed_kmh)} km/h`
                  : "—"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">Avg speed</div>
            </div>
          </div>

          {/* Odometer row */}
          {(t.odometer_start_km != null || t.odometer_end_km != null) && (
            <div className="text-center mt-2">
              <div className="text-xs text-gray-500">
                Odometer:{" "}
                <span className="text-gray-300">
                  {t.odometer_start_km != null ? `${Math.round(t.odometer_start_km).toLocaleString()} km` : "—"}
                  <span className="text-gray-600 mx-1">→</span>
                  {t.odometer_end_km != null ? `${Math.round(t.odometer_end_km).toLocaleString()} km` : "—"}
                </span>
              </div>
            </div>
          )}

          <div className="flex items-center justify-between mt-2">
            {t.duration_min != null ? (
              <span className="text-xs text-gray-600">{formatDuration(t.duration_min)}</span>
            ) : <span />}
            <ChevronDown
              size={14}
              className={clsx(
                "text-gray-600 transition-transform",
                expandedId === t.id && "rotate-180"
              )}
            />
          </div>

          {expandedId === t.id && (
            <TripMap
              points={routeCache[t.id] ?? []}
              mapId={`trip-map-${t.id}`}
            />
          )}
            </>
          )}
        </div>
      ))}
    </div>
  );
}
