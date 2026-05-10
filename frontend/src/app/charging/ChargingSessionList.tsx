"use client";
import { useState } from "react";
import { Zap, Pencil, X, Check, MapPin, Trash2, ChevronDown } from "lucide-react";
import ChargingCurve from "@/components/ChargingCurve";
import type { ChargingSession } from "@/lib/types";
import { api } from "@/lib/api";
import clsx from "clsx";
import { useTimezone } from "@/app/SettingsProvider";
import { fmtDateTime } from "@/lib/format";

interface Props {
  sessions: ChargingSession[];
  total: number;
  onSessionUpdated: (updated: ChargingSession) => void;
  onSessionDeleted?: (id: number) => void;
}

interface EditState {
  soc_start_pct: string;
  soc_end_pct: string;
  kwh_added: string;
  kwh_added_real: string;
  cost: string;
  cost_per_kwh: string;
  charge_type: string;
  peak_power_kw: string;
  location_name: string;
}

function formatDuration(min: number | null) {
  if (min == null) return null;
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function sessionToEditState(s: ChargingSession): EditState {
  return {
    soc_start_pct: s.soc_start_pct?.toString() ?? "",
    soc_end_pct: s.soc_end_pct?.toString() ?? "",
    kwh_added: s.kwh_added?.toString() ?? "",
    kwh_added_real: s.kwh_added_real?.toString() ?? "",
    cost: s.cost?.toString() ?? "",
    cost_per_kwh: s.cost_per_kwh?.toString() ?? "",
    charge_type: s.charge_type ?? "AC",
    peak_power_kw: s.peak_power_kw?.toString() ?? "",
    location_name: s.location_name ?? "",
  };
}

export default function ChargingSessionList({ sessions, total, onSessionUpdated, onSessionDeleted }: Props) {
  const tz = useTimezone();
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  function startEdit(s: ChargingSession) {
    setEditingId(s.id);
    setEditState(sessionToEditState(s));
    setSaveError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditState(null);
    setSaveError(null);
  }

  async function saveEdit(s: ChargingSession) {
    if (!editState) return;
    setSaving(true);
    setSaveError(null);
    try {
      const body: Record<string, unknown> = {};
      if (editState.soc_start_pct !== "") body.soc_start_pct = parseFloat(editState.soc_start_pct);
      if (editState.soc_end_pct !== "") body.soc_end_pct = parseFloat(editState.soc_end_pct);
      if (editState.kwh_added !== "") body.kwh_added = parseFloat(editState.kwh_added);
      if (editState.kwh_added_real !== "") body.kwh_added_real = parseFloat(editState.kwh_added_real);
      if (editState.cost_per_kwh !== "") body.cost_per_kwh = parseFloat(editState.cost_per_kwh);
      if (editState.cost !== "") body.cost = parseFloat(editState.cost);
      if (editState.charge_type) body.charge_type = editState.charge_type;
      if (editState.peak_power_kw !== "") body.peak_power_kw = parseFloat(editState.peak_power_kw);
      body.location_name = editState.location_name || null;

      const updated = await api.charging.updateSession(s.id, body as Partial<ChargingSession>);
      onSessionUpdated(updated);
      setEditingId(null);
      setEditState(null);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (!sessions.length) {
    return (
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-6 text-center text-gray-500">
        No charging sessions recorded yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-gray-500 uppercase tracking-wider px-1">
        All sessions ({total})
      </div>
      {sessions.map((s) => {
        const isEditing = editingId === s.id;
        return (
          <div
            key={s.id}
            className="rounded-2xl bg-[#161b27] border border-white/5 p-4"
          >
            <div className="flex items-center justify-between mb-2">
              <div className="flex flex-col">
                <div className="text-sm text-white font-medium">{fmtDateTime(s.started_at, tz)}</div>
                {s.location_name && (
                  <div className="flex items-center gap-1 text-xs text-gray-500 mt-0.5">
                    <MapPin size={10} className="text-[#00B0F0] shrink-0" />
                    <span className="truncate max-w-[180px]">{s.location_name}</span>
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2">
                {!isEditing && (
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
                )}
                {!isEditing ? (
                  <div className="flex gap-1">
                    <button
                      onClick={() => startEdit(s)}
                      className="p-1 text-gray-600 hover:text-gray-300 transition"
                      title="Edit session"
                    >
                      <Pencil size={13} />
                    </button>
                    {onSessionDeleted && (
                      <button
                        onClick={async () => {
                          if (!confirm("Delete this session?")) return;
                          setDeletingId(s.id);
                          try {
                            await api.charging.deleteSession(s.id);
                            onSessionDeleted(s.id);
                          } catch {
                            // ignore
                          } finally {
                            setDeletingId(null);
                          }
                        }}
                        disabled={deletingId === s.id}
                        className="p-1 text-gray-600 hover:text-red-400 transition disabled:opacity-40"
                        title="Delete session"
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="flex gap-1">
                    <button
                      onClick={() => saveEdit(s)}
                      disabled={saving}
                      className="p-1 text-green-400 hover:text-green-300 disabled:opacity-50 transition"
                      title="Save"
                    >
                      <Check size={15} />
                    </button>
                    <button
                      onClick={cancelEdit}
                      className="p-1 text-gray-500 hover:text-gray-300 transition"
                      title="Cancel"
                    >
                      <X size={15} />
                    </button>
                  </div>
                )}
              </div>
            </div>

            {isEditing && editState ? (
              <div className="flex flex-col gap-2">
                <div className="grid grid-cols-2 gap-2">
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-gray-500">SoC start %</span>
                    <input
                      type="number"
                      value={editState.soc_start_pct}
                      onChange={(e) => setEditState({ ...editState, soc_start_pct: e.target.value })}
                      className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-gray-500">SoC end %</span>
                    <input
                      type="number"
                      value={editState.soc_end_pct}
                      onChange={(e) => setEditState({ ...editState, soc_end_pct: e.target.value })}
                      className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-gray-500">kWh estimated</span>
                    <input
                      type="number"
                      step="0.01"
                      value={editState.kwh_added}
                      onChange={(e) => setEditState({ ...editState, kwh_added: e.target.value })}
                      className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-gray-500">kWh actual</span>
                    <input
                      type="number"
                      step="0.01"
                      value={editState.kwh_added_real}
                      onChange={(e) => setEditState({ ...editState, kwh_added_real: e.target.value })}
                      className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-gray-500">Cost per kWh</span>
                    <input
                      type="number"
                      step="0.001"
                      value={editState.cost_per_kwh}
                      onChange={(e) => setEditState({ ...editState, cost_per_kwh: e.target.value })}
                      className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-gray-500">Cost</span>
                    <input
                      type="number"
                      step="0.01"
                      value={editState.cost}
                      onChange={(e) => setEditState({ ...editState, cost: e.target.value })}
                      className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-gray-500">Type</span>
                    <select
                      value={editState.charge_type}
                      onChange={(e) => setEditState({ ...editState, charge_type: e.target.value })}
                      className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white"
                    >
                      <option value="AC">AC</option>
                      <option value="DC">DC</option>
                    </select>
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-gray-500">Peak power kW</span>
                    <input
                      type="number"
                      step="0.1"
                      value={editState.peak_power_kw}
                      onChange={(e) => setEditState({ ...editState, peak_power_kw: e.target.value })}
                      className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white"
                    />
                  </label>
                </div>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-gray-500">Location name</span>
                  <input
                    type="text"
                    value={editState.location_name}
                    onChange={(e) => setEditState({ ...editState, location_name: e.target.value })}
                    placeholder="e.g. Home, Work, Tesla Supercharger"
                    className="rounded-lg bg-[#0d1117] border border-white/10 px-2 py-1.5 text-sm text-white w-full"
                  />
                </label>
                {saveError && <div className="text-xs text-red-400">{saveError}</div>}
              </div>
            ) : (
              <>
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
                      {s.kwh_added != null ? s.kwh_added : "—"}
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

                <div className="grid grid-cols-4 gap-2 text-center mt-3">
                  <div>
                    <div className="text-sm font-medium text-white">
                      {s.range_added_km != null ? `${s.range_added_km} km` : "—"}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">Range added</div>
                  </div>
                  <div>
                    <div className="text-sm font-medium text-white">
                      {s.peak_power_kw != null ? `${s.peak_power_kw} kW` : "—"}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">Peak</div>
                  </div>
                  <div>
                    <div className="text-sm font-medium text-white">
                      {s.avg_power_kw != null ? `${s.avg_power_kw} kW` : "—"}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">Avg power</div>
                  </div>
                  <div>
                    <div className="text-sm font-medium text-white">
                      {s.cost_per_kwh != null
                        ? s.currency_after
                          ? `${s.cost_per_kwh} ${s.currency_symbol}`
                          : `${s.currency_symbol}${s.cost_per_kwh}`
                        : "—"}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">per kWh</div>
                  </div>
                </div>

                {s.duration_min != null && (
                  <div className="text-xs text-gray-600 mt-2 text-right">
                    {formatDuration(s.duration_min)}
                  </div>
                )}

                <button
                  type="button"
                  onClick={() => setExpandedId(expandedId === s.id ? null : s.id)}
                  className="w-full flex items-center justify-center gap-1 mt-2 text-xs text-gray-600 hover:text-gray-400 transition"
                >
                  <ChevronDown
                    size={13}
                    className={clsx("transition-transform", expandedId === s.id && "rotate-180")}
                  />
                  {expandedId === s.id ? "Hide curve" : "Show curve"}
                </button>

                {expandedId === s.id && <ChargingCurve sessionId={s.id} />}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
