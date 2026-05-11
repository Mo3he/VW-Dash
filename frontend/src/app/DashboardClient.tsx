"use client";
import { useState } from "react";
import {
  Lock, Unlock, Plug, Thermometer, Zap, Wind, Gauge,
} from "lucide-react";
import SocGauge from "@/components/SocGauge";
import StatusCard from "@/components/StatusCard";
import SocHistory from "@/components/SocHistory";
import EventsFeed from "@/components/EventsFeed";
import VampireDrainCard from "@/components/VampireDrainCard";
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
    notReadyForCharging: "Not charging",
    readyForCharging: "Plugged in",
    READY_FOR_CHARGING: "Plugged in",
    NOT_READY_FOR_CHARGING: "Not charging",
    CHARGE_PURPOSE_REACHED_NOT_CONSERVATION_MODE: "Charge complete",
    CONSERVATION: "Conservation mode",
    OFF: "Not charging",
  };
  return map[state] ?? state;
}

function climateLabel(state: string | null) {
  if (!state) return null;
  const map: Record<string, string> = {
    COOLING: "Cooling",
    HEATING: "Heating",
    OFF: null as unknown as string,
    off: null as unknown as string,
  };
  return map[state] ?? (state === "OFF" || state === "off" ? null : state);
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

export default function DashboardClient({ initial, history }: Props) {
  const { data: live, connected } = useVehicleLive();
  const tz = useTimezone();
  const hour12 = useHour12();
  const distanceUnit = useDistanceUnit();
  const [climateLoading, setClimateLoading] = useState(false);
  const [climateMsg, setClimateMsg] = useState<string | null>(null);

  const soc = live?.soc_pct ?? initial?.soc_pct ?? null;
  const rangeKm = live?.range_km ?? initial?.range_km ?? null;
  const chargingState = live?.charging_state ?? initial?.charging_state ?? null;
  const chargePower = live?.charge_power_kw ?? initial?.charge_power_kw ?? null;
  const chargeRate = live?.charge_rate_km_h ?? initial?.charge_rate_km_h ?? null;
  const chargeType = live?.charge_type ?? initial?.charge_type ?? null;
  const plugged = live?.plug_connected ?? initial?.plug_connected ?? null;
  const locked = live?.locked ?? initial?.locked ?? null;
  const batteryTempC = live?.battery_temp_c ?? initial?.battery_temp_c ?? null;
  const cabinTempC = live?.cabin_temp_c ?? initial?.cabin_temp_c ?? null;
  const climatisationState = live?.climatisation_state ?? initial?.climatisation_state ?? null;
  const targetSoc = live?.target_soc_pct ?? initial?.target_soc_pct ?? null;
  const remainingMin = live?.remaining_charge_time_min ?? initial?.remaining_charge_time_min ?? null;
  const parkingTime = initial?.parking_time ?? null;
  const odometer = initial?.odometer_km ?? null;

  const recordedAt = live?.recorded_at ?? initial?.recorded_at ?? null;
  const carCapturedAt = live?.car_captured_at ?? initial?.car_captured_at ?? null;
  const isCharging = chargingState === "CHARGING";
  const isClimateActive = climatisationState != null &&
    climatisationState !== "OFF" &&
    climatisationState !== "off" &&
    climatisationState !== "";
  const activeClimateLabel = climateLabel(climatisationState);

  async function handleClimate(action: "start" | "stop") {
    setClimateLoading(true);
    setClimateMsg(null);
    try {
      await api.vehicle.climate(action);
      setClimateMsg(action === "start" ? "Climate started — updating next poll" : "Climate stopped — updating next poll");
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
      </div>

      {soc != null ? (
        <div className="rounded-2xl bg-[#161b27] border border-white/5 p-6 flex justify-center">
          <SocGauge soc={soc} rangeKm={rangeKm} targetSoc={targetSoc} />
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
          sub={chargeType && isCharging ? chargeType : undefined}
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

        {isCharging && chargePower != null ? (
          <StatusCard
            label="Charge power"
            value={
              <span className="flex items-center gap-1.5">
                <Zap size={16} className="text-yellow-400" />
                {chargePower.toFixed(1)} kW
              </span>
            }
            sub={
              remainingMin
                ? `~${remainingMin} min remaining`
                : chargeRate != null
                ? distanceUnit === "miles"
                  ? `+${(chargeRate * 0.621371).toFixed(0)} mph`
                  : `+${chargeRate.toFixed(0)} km/h`
                : undefined
            }
          />
        ) : null}

        {isClimateActive && activeClimateLabel ? (
          <StatusCard
            label="Climate"
            value={
              <span className="flex items-center gap-1.5">
                <Wind size={16} className="text-cyan-400" />
                {activeClimateLabel}
              </span>
            }
            sub={cabinTempC != null ? `Target ${cabinTempC.toFixed(1)}°C` : undefined}
          />
        ) : null}

        <StatusCard
          label="Battery temp"
          value={
            batteryTempC != null ? (
              <span className="flex items-center gap-1.5">
                <Thermometer size={16} className="text-orange-400" />
                {batteryTempC.toFixed(1)}°C
              </span>
            ) : (
              "—"
            )
          }
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
      </div>

      {/* Climate control */}
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Climate control</div>
        <div className="flex gap-3">
          <button
            onClick={() => handleClimate("start")}
            disabled={climateLoading || isClimateActive}
            className="flex-1 flex items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-medium
              bg-cyan-500/10 text-cyan-400 border border-cyan-500/20
              hover:bg-cyan-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            <Wind size={15} />
            Start AC
          </button>
          <button
            onClick={() => handleClimate("stop")}
            disabled={climateLoading || !isClimateActive}
            className="flex-1 flex items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-medium
              bg-gray-500/10 text-gray-300 border border-white/10
              hover:bg-gray-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            Stop AC
          </button>
        </div>
        {climateMsg && (
          <div className={`mt-2 text-xs text-center ${climateMsg.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
            {climateMsg}
          </div>
        )}
        {cabinTempC != null && (
          <div className="mt-2 text-xs text-gray-500 text-center">
            Target cabin temp: {cabinTempC.toFixed(1)}°C
          </div>
        )}
      </div>

      {history.length > 1 && <SocHistory initialData={history} />}

      <VampireDrainCard />

      <EventsFeed pollTrigger={live?.recorded_at} />

    </div>
  );
}
