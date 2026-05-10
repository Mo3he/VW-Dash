"use client";
import { createContext, useContext } from "react";

interface AppSettings {
  timezone: string;
  vehicleName: string | null;
}

const SettingsContext = createContext<AppSettings>({ timezone: "UTC", vehicleName: null });

export function SettingsProvider({
  children,
  timezone,
  vehicleName,
}: {
  children: React.ReactNode;
  timezone: string;
  vehicleName: string | null;
}) {
  return (
    <SettingsContext.Provider value={{ timezone, vehicleName }}>
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
