"use client";
import { useState, useEffect } from "react";
import {
  Lock, Unlock, Plug, Thermometer, Wind, Gauge, RefreshCw,
} from "lucide-react";
import SocGauge from "@/components/SocGauge";
import ChargingGauge from "@/components/ChargingGauge";
import StatusCard from "@/components/StatusCard";
import SocHistory from "@/components/SocHistory";
import EventsFeed from "@/components/EventsFeed";
import VampireDrainCard from "@/components/VampireDrainCard";
import WindowStatus from "@/components/WindowStatus";
import { useVehicleLive } from "@/hooks/useVehicleLive";
import type { VehicleSnapshot } from "@/lib/types";
import { api } from "@/lib/api";
import { useTimezone, useHour12, useDistanceUnit } from "./SettingsProvider";
import { fmtTime } from "@/lib/format";

interface Props {
  initial: VehicleSnapshot | null;
  history: VehicleSnapshot[];
}

function chargingLabel(state: string | null) {
  if (!state) return "Unknown";
  const map: Record<string, string> = {
    CHARGING: "Charging",
    charging: "Charging",
    notReadyForCharging: "Not charging",
    readyForCharging: "Plugged in",
    READY_FOR_CHARGING: "Plugged in",
    NOT_READY_FOR_CHARGING: "Not charging",
    CHARGE_PURPOSE_REACHED_NOT_CONSERVATION_MODE: "Not charging",
    chargePurposeReachedAndNotConservationCharging: "Not charging",
    CONSERVATION: "Conservation mode",
    OFF: "Not charging",
  };
  return map[state] ?? state;
}

function climateLabel(state: string | null): string | null {
  if (!state) return null;
  const s = state.toLowerCase();
  if (s === "off" || s === "invalid") return null;
  const map: Record<string, string> = {
    heating: "Heating",
    cooling: "Cooling",
    ventilation: "Ventilating",
  };
  return map[s] ?? state;
}

function formatParkingDuration(parkingTime: string | null): string | null {
  if (!parkingTime) return null;
  const parked = new Date(parkingTime);
  const diffMs = Date.now() - parked.getTime();
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin < 60) return `Parked ${diffMin}m ago`;
  const h = Math.floor(diffMin / 60);
  const m = diffMin % 60;
  return m > 0 ? `Parked ${h}h ${m}m ago` : `Parked ${h}h ago`;
}

export default function DashboardClient({ initial: initialProp, history: historyProp }: Props) {
  const { data: live, connected } = useVehicleLive();
  const tz = useTimezone();
  const hour12 = useHour12();
  const distanceUnit = useDistanceUnit();
  const [initial, setInitial] = useState<VehicleSnapshot | null>(initialProp);
  const [history, setHistory] = useState<VehicleSnapshot[]>(historyProp);

  // Fetch initial data client-side (token is in localStorage, not available to SSR)
  useEffect(() => {
    api.vehicle.latest().then(setInitial).catch(() => {});
    api.vehicle.history(24).then(setHistory).catch(() => {});
  }, []);

  const [climateLoading, setClimateLoading] = useState(false);
  const [climateMsg, setClimateMsg] = useState<string | null>(null);
  const [chargingControlLoading, setChargingControlLoading] = useState(false);
  const [chargingControlMsg, setChargingControlMsg] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  async function handleForcePoll() {
    setPolling(true);
    try {
      await api.vehicle.poll();
      // Re-fetch latest snapshot in case WS delivery is slow/disconnected
      const latest = await api.vehicle.latest().catch(() => null);
      if (latest) setInitial(latest);
    } catch {
      // ignore
    } finally {
      setPolling(false);
    }
  }

  const soc = live?.soc_pct ?? initial?.soc_pct ?? null;
  const rangeKm = live?.range_km ?? initial?.range_km ?? null;
  const chargingState = live?.charging_state ?? initial?.charging_state ?? null;
  const chargePower = live?.charge_power_kw ?? initial?.charge_power_kw ?? null;
  const chargeRate = live?.charge_rate_km_h ?? initial?.charge_rate_km_h ?? null;
  const chargeType = live?.charge_type ?? initial?.charge_type ?? null;
  const plugged = live?.plug_connected ?? initial?.plug_connected ?? null;
  const locked = live?.locked ?? initial?.locked ?? null;
  const windows = live?.windows ?? initial?.windows ?? null;
  const batteryTempMinC = live?.battery_temp_min_c ?? initial?.battery_temp_min_c ?? null;
  const batteryTempMaxC = live?.battery_temp_max_c ?? initial?.battery_temp_max_c ?? null;
  // fallback to legacy average column for old snapshots that lack min/max
  const batteryTempC = live?.battery_temp_c ?? initial?.battery_temp_c ?? null;
  const cabinTempC = live?.cabin_temp_c ?? initial?.cabin_temp_c ?? null;
  const climatisationState = live?.climatisation_state ?? initial?.climatisation_state ?? null;
  const targetSoc = live?.target_soc_pct ?? initial?.target_soc_pct ?? null;
  const remainingMin = live?.remaining_charge_time_min ?? initial?.remaining_charge_time_min ?? null;
  const parkingTime = initial?.parking_time ?? null;
  const odometer = initial?.odometer_km ?? null;

  const recordedAt = live?.recorded_at ?? initial?.recorded_at ?? null;
  const carCapturedAt = live?.car_captured_at ?? initial?.car_captured_at ?? null;
  const isCharging = chargingState?.toUpperCase() === "CHARGING";
  const isClimateActive = climatisationState != null &&
    climatisationState !== "OFF" &&
    climatisationState !== "off" &&
    climatisationState !== "";
  const activeClimateLabel = climateLabel(climatisationState);

  async function handleChargingControl(action: "start" | "stop") {
    setChargingControlLoading(true);
    setChargingControlMsg(null);
    try {
      await api.vehicle.chargingControl(action);
      setChargingControlMsg(action === "start" ? "Charging started — refreshing in 30s…" : "Charging stopped — refreshing in 30s…");
      setTimeout(async () => {
        try {
          await api.vehicle.poll();
          const latest = await api.vehicle.latest().catch(() => null);
          if (latest) setInitial(latest);
          setChargingControlMsg(null);
        } catch {
          setChargingControlMsg(null);
        }
      }, 30_000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setChargingControlMsg(`Error: ${msg}`);
    } finally {
      setChargingControlLoading(false);
    }
  }

  async function handleClimate(action: "start" | "stop") {
    setClimateLoading(true);
    setClimateMsg(null);
    try {
      await api.vehicle.climate(action);
      setClimateMsg(action === "start" ? "Climate started — refreshing in 30s…" : "Climate stopped — refreshing in 30s…");
      // Trigger a poll after 30 s so the UI reflects the new climate state
      setTimeout(async () => {
        try {
          await api.vehicle.poll();
          const latest = await api.vehicle.latest().catch(() => null);
          if (latest) setInitial(latest);
          setClimateMsg(null);
        } catch {
          setClimateMsg(null);
        }
      }, 30_000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setClimateMsg(`Error: ${msg}`);
    } finally {
      setClimateLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between">
        <div>
          {!connected && (
            <span className="inline-flex items-center gap-1 rounded-full bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-xs px-2 py-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
              Offline
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <div className="flex flex-col items-end gap-0.5">
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <span className="text-gray-600">Car</span>
              {carCapturedAt ? fmtTime(carCapturedAt, tz, hour12) : "—"}
            </div>
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <span className="text-gray-600">Server</span>
              {recordedAt ? fmtTime(recordedAt, tz, hour12) : "—"}
            </div>
          </div>
          <button
            onClick={handleForcePoll}
            disabled={polling}
            title="Force poll"
            className="p-1.5 rounded-lg text-gray-500 hover:text-[#00B0F0] hover:bg-white/5 transition-colors disabled:opacity-40"
          >
            <RefreshCw size={15} className={polling ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {soc != null ? (
        <div className="rounded-2xl bg-[#161b27] border border-white/5 px-2 py-4 sm:p-6 overflow-visible">
          <div className="flex items-end justify-around gap-1 sm:gap-4">
              {/* Charge power gauge — 0–150 kW range covers AC & DC */}
              <ChargingGauge
                label="Charge power"
                value={isCharging && chargePower != null ? `${chargePower.toFixed(1)} kW` : "—"}
                fill={isCharging && chargePower != null ? chargePower / 150 : 0}
                color="#facc15"
              />
              {/* Centre: SoC (full size) */}
              <SocGauge soc={soc} rangeKm={rangeKm} targetSoc={targetSoc} showLabel />
              {/* Remaining time gauge */}
              <ChargingGauge
                label="Remaining"
                value={
                  isCharging && remainingMin != null
                    ? remainingMin < 60
                      ? `${remainingMin} min`
                      : `${Math.floor(remainingMin / 60)}h ${remainingMin % 60}m`
                    : "—"
                }
                sub={
                  isCharging && remainingMin != null
                    ? (() => {
                        const finish = new Date(Date.now() + remainingMin * 60000);
                        return finish.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
                      })()
                    : null
                }
                fill={
                  isCharging && remainingMin != null && targetSoc != null && soc != null
                    ? 1 - Math.min(1, remainingMin / Math.max(1, ((targetSoc - soc) / 100) * 600))
                    : isCharging && remainingMin != null
                    ? 1 - Math.min(1, remainingMin / 600)
                    : 0
                }
                color="#00B0F0"
              />
            </div>
        </div>
      ) : (
        <div className="rounded-2xl bg-[#161b27] border border-white/5 p-6 text-center text-gray-500">
          Waiting for data…
        </div>
      )}

      {/* Primary status row */}
      <div className="grid grid-cols-2 gap-3">
        <StatusCard
          label="Status"
          value={
            <span className="flex items-center gap-1.5">
              {plugged ? <Plug size={16} className="text-[#00B0F0]" /> : null}
              {chargingLabel(chargingState)}
            </span>
          }
          accent={isCharging}
          sub={chargeType && isCharging ? chargeType.toUpperCase() : undefined}
        />

        <StatusCard
          label="Locked"
          value={
            <span className="flex items-center gap-1.5">
              {locked ? (
                <Lock size={16} className="text-green-400" />
              ) : (
                <Unlock size={16} className="text-yellow-400" />
              )}
              {locked == null ? "Unknown" : locked ? "Locked" : "Unlocked"}
            </span>
          }
        />

        <StatusCard
          label="Battery temp"
          value={
            batteryTempMinC != null && batteryTempMaxC != null ? (
              <span className="flex items-center gap-1.5">
                <Thermometer size={16} className="text-orange-400" />
                {batteryTempMinC.toFixed(1)}°C – {batteryTempMaxC.toFixed(1)}°C
              </span>
            ) : batteryTempC != null ? (
              <span className="flex items-center gap-1.5">
                <Thermometer size={16} className="text-orange-400" />
                {batteryTempC.toFixed(1)}°C
              </span>
            ) : (
              "—"
            )
          }
          sub={batteryTempMinC != null && batteryTempMaxC != null ? "min – max" : undefined}
        />

        <StatusCard
          label="Odometer"
          value={
            odometer != null
              ? (
                <span className="flex items-center gap-1.5">
                  <Gauge size={16} className="text-gray-400" />
                  {distanceUnit === "miles"
                    ? `${Math.round(odometer * 0.621371).toLocaleString("sv-SE")} mi`
                    : `${Math.round(odometer).toLocaleString("sv-SE")} km`}
                </span>
              )
              : "—"
          }
          sub={formatParkingDuration(parkingTime) ?? undefined}
        />

        <StatusCard
          label="Climate"
          value={
            isClimateActive && activeClimateLabel ? (
              <span className="flex items-center gap-1.5">
                <Wind size={16} className="text-cyan-400" />
                {activeClimateLabel}
              </span>
            ) : (
              <span className="text-gray-500">Off</span>
            )
          }
          sub={isClimateActive && cabinTempC != null ? `Target ${cabinTempC.toFixed(1)}°C` : undefined}
        />

        {windows && Object.keys(windows).length > 0 && (
          <WindowStatus windows={windows} />
        )}

        {/* Climate control */}
        <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4 flex flex-col gap-3">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Climate control</div>
          <button
            onClick={() => handleClimate(isClimateActive ? "stop" : "start")}
            disabled={climateLoading}
            className={`w-full flex items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-medium
              disabled:opacity-40 disabled:cursor-not-allowed transition
              ${isClimateActive
                ? "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 hover:bg-yellow-500/20"
                : "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20"}`}
          >
            <Wind size={15} />
            {isClimateActive ? "Stop AC" : "Start AC"}
          </button>
          {climateMsg && (
            <div className={`text-xs text-center ${climateMsg.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
              {climateMsg}
            </div>
          )}
        </div>

        {/* Charging control */}
        <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4 flex flex-col gap-3">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Charging control</div>
          <button
            onClick={() => handleChargingControl(isCharging ? "stop" : "start")}
            disabled={chargingControlLoading || (!plugged && !isCharging)}
            className={`w-full flex items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-medium
              disabled:opacity-40 disabled:cursor-not-allowed transition
              ${isCharging
                ? "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 hover:bg-yellow-500/20"
                : "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20"}`}
          >
            <Plug size={15} />
            {isCharging ? "Stop Charging" : "Start Charging"}
          </button>
          {chargingControlMsg && (
            <div className={`text-xs text-center ${chargingControlMsg.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
              {chargingControlMsg}
            </div>
          )}
        </div>
      </div>

      {history.length > 1 && <SocHistory initialData={history} />}

      <VampireDrainCard />

      <EventsFeed pollTrigger={live?.recorded_at} />

    </div>
  );
}
