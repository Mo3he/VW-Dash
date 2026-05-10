import type { Metadata, Viewport } from "next";
import "./globals.css";
import Nav from "@/components/Nav";
import { SettingsProvider } from "./SettingsProvider";
import AuthGate from "@/components/AuthGate";

export const metadata: Metadata = {
  title: "VW Dash",
  description: "ID.4 monitoring dashboard",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

async function getServerSettings(): Promise<{ timezone: string; vehicleName: string | null }> {
  try {
    const res = await fetch("http://localhost:8000/api/settings", { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      return { timezone: data.timezone || "UTC", vehicleName: data.vehicle_name ?? null };
    }
  } catch {}
  return { timezone: "UTC", vehicleName: null };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const { timezone, vehicleName } = await getServerSettings();
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#0f1117]">
        <AuthGate>
          <SettingsProvider timezone={timezone} vehicleName={vehicleName}>
            <Nav />
            <main className="max-w-4xl mx-auto px-4 pb-24 pt-4">{children}</main>
          </SettingsProvider>
        </AuthGate>
      </body>
    </html>
  );
}
