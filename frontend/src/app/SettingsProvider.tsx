"use client";
import { createContext, useContext } from "react";

const TimezoneContext = createContext("UTC");

export function SettingsProvider({
  children,
  timezone,
}: {
  children: React.ReactNode;
  timezone: string;
}) {
  return (
    <TimezoneContext.Provider value={timezone}>
      {children}
    </TimezoneContext.Provider>
  );
}

export function useTimezone(): string {
  return useContext(TimezoneContext);
}
