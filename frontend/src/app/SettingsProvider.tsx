"use client";
import { createContext, useContext, useEffect, useState } from "react";

interface AppSettings {
  timezone: string;
  vehicleName: string | null;
  time24h: boolean;
  distanceUnit: "km" | "miles";
}

const SettingsContext = createContext<AppSettings>({
  timezone: "UTC",
  vehicleName: null,
  time24h: false,
  distanceUnit: "km",
});

export function SettingsProvider({
  children,
  timezone,
  vehicleName,
  time24h,
  distanceUnit,
}: {
  children: React.ReactNode;
  timezone: string;
  vehicleName: string | null;
  time24h: boolean;
  distanceUnit: "km" | "miles";
}) {
  // Initialise with the SSR values so there's no flash, then override with a
  // fresh client-side fetch. This ensures that a stale/failed SSR fetch (e.g.
  // when the backend starts slower than Next.js after a container restart) is
  // corrected as soon as the browser loads without needing a re-save.
  const [settings, setSettings] = useState<AppSettings>({
    timezone, vehicleName, time24h, distanceUnit,
  });

  useEffect(() => {
    fetch("/api/settings", { cache: "no-store" })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (!data) return;
        setSettings({
          timezone: data.timezone || "UTC",
          vehicleName: data.vehicle_name ?? null,
          time24h: data.time_24h ?? false,
          distanceUnit: data.distance_unit === "miles" ? "miles" : "km",
        });
      })
      .catch(() => {});
  }, []);

  return (
    <SettingsContext.Provider value={settings}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useTimezone(): string {
  return useContext(SettingsContext).timezone;
}

export function useVehicleName(): string | null {
  return useContext(SettingsContext).vehicleName;
}

export function useHour12(): boolean {
  return !useContext(SettingsContext).time24h;
}

export function useDistanceUnit(): "km" | "miles" {
  return useContext(SettingsContext).distanceUnit;
}
