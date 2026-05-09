"use client";
import { Lock, Unlock, Plug, Thermometer, Zap, Clock } from "lucide-react";
import SocGauge from "@/components/SocGauge";
import StatusCard from "@/components/StatusCard";
import SocHistory from "@/components/SocHistory";
import { useVehicleLive } from "@/hooks/useVehicleLive";
import type { VehicleSnapshot } from "@/lib/types";

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

export default function DashboardClient({ initial, history }: Props) {
  const { data: live, connected } = useVehicleLive();

  const soc = live?.soc_pct ?? initial?.soc_pct ?? null;
  const rangeKm = initial?.range_km ?? null;
  const chargingState = live?.charging_state ?? initial?.charging_state ?? null;
  const chargePower = live?.charge_power_kw ?? initial?.charge_power_kw ?? null;
  const plugged = live?.plug_connected ?? initial?.plug_connected ?? null;
  const locked = live?.locked ?? initial?.locked ?? null;
  const batteryTempC = initial?.battery_temp_c ?? null;
  const targetSoc = initial?.target_soc_pct ?? null;
  const remainingMin = initial?.remaining_charge_time_min ?? null;

  const isCharging = chargingState === "CHARGING";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 justify-end">
        <span
          className={`w-2 h-2 rounded-full ${connected ? "bg-green-400 animate-pulse" : "bg-gray-600"}`}
        />
        <span className="text-xs text-gray-500">{connected ? "Live" : "Offline"}</span>
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
            sub={remainingMin ? `~${remainingMin} min remaining` : undefined}
          />
        ) : (
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
        )}

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
            initial?.odometer_km != null
              ? `${Math.round(initial.odometer_km).toLocaleString("sv-SE")} km`
              : "—"
          }
        />
      </div>

      {history.length > 1 && <SocHistory data={history} />}

      {(live?.recorded_at ?? initial?.recorded_at) && (
        <div className="flex items-center gap-1.5 justify-center text-xs text-gray-600">
          <Clock size={12} />
          Last updated{" "}
          {new Date(live?.recorded_at ?? initial!.recorded_at).toLocaleTimeString("sv-SE")}
        </div>
      )}
    </div>
  );
}
