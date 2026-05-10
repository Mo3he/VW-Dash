import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";
import { SettingsProvider } from "./SettingsProvider";

export const metadata: Metadata = {
  title: "VW Dash",
  description: "ID.4 monitoring dashboard",
  viewport: "width=device-width, initial-scale=1, maximum-scale=1",
};

async function getTimezone(): Promise<string> {
  try {
    const base = typeof window === "undefined" ? "http://localhost:8000/api" : "/api";
    const res = await fetch(`${base}/settings`, { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      return data.timezone || "UTC";
    }
  } catch {}
  return "UTC";
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const timezone = await getTimezone();
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#0f1117]">
        <SettingsProvider timezone={timezone}>
          <Nav />
          <main className="max-w-4xl mx-auto px-4 pb-24 pt-4">{children}</main>
        </SettingsProvider>
      </body>
    </html>
  );
}
