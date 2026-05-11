"use client";
import { createContext, useContext } from "react";

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
  return (
    <SettingsContext.Provider value={{ timezone, vehicleName, time24h, distanceUnit }}>
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
