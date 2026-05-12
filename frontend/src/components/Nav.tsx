"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { BatteryCharging, Car, MapPin, Settings, Route, LogOut, Sun, Moon, Github, Coffee, BarChart2 } from "lucide-react";
import clsx from "clsx";
import { useVehicleName } from "@/app/SettingsProvider";
import { authHeaders, clearAuth, getUsername } from "@/lib/auth";
import { useTheme, useToggleTheme } from "@/components/ThemeProvider";

const links = [
  { href: "/", label: "Status", Icon: Car },
  { href: "/charging", label: "Charging", Icon: BatteryCharging },
  { href: "/trips", label: "Trips", Icon: MapPin },
  { href: "/journeys", label: "Journeys", Icon: Route },
  { href: "/stats", label: "Statistics", Icon: BarChart2 },
  { href: "/settings", label: "Settings", Icon: Settings },
];

export default function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const vehicleName = useVehicleName();
  const [version, setVersion] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const theme = useTheme();
  const toggleTheme = useToggleTheme();

  useEffect(() => {
    setUsername(getUsername());
  }, []);

  function handleLogout() {
    clearAuth();
    router.refresh();
  }

  useEffect(() => {
    fetch("/api/version", { headers: authHeaders() })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setVersion(d.version ?? null))
      .catch(() => {});
  }, []);

  return (
    <>
      {/* Top bar */}
      <header className="sticky top-0 z-10 bg-[#0f1117]/90 backdrop-blur-md border-b border-white/5 px-5 h-12 flex items-center gap-2.5">
        <span className="text-white font-semibold text-sm tracking-tight">VW Dash</span>
        {vehicleName && (
          <>
            <span className="text-white/15 text-xs">/</span>
            <span className="text-[#00B0F0] text-xs font-medium">{vehicleName}</span>
          </>
        )}
        {version && (
          <span className="text-white/20 text-[10px] font-mono">v{version}</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {username && (
            <span className="text-white/30 text-xs hidden sm:inline">{username}</span>
          )}
          <button
            onClick={toggleTheme}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            className="p-1.5 rounded-lg text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors"
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <a
            href="https://github.com/Mo3he/VW-Dash"
            target="_blank"
            rel="noopener noreferrer"
            title="GitHub"
            className="p-1.5 rounded-lg text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors"
          >
            <Github size={15} />
          </a>
          <a
            href="https://buymeacoffee.com/Mo3he"
            target="_blank"
            rel="noopener noreferrer"
            title="Buy me a coffee"
            className="p-1.5 rounded-lg text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors"
          >
            <Coffee size={15} />
          </a>
          <button
            onClick={handleLogout}
            title="Sign out"
            className="p-1.5 rounded-lg text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors"
          >
            <LogOut size={15} />
          </button>
        </div>
      </header>

      {/* Bottom tab bar (mobile) */}
      <nav className="fixed bottom-0 left-0 right-0 z-10 bg-[#0a0d14] border-t border-white/10 flex">
        {links.map(({ href, label, Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex-1 flex flex-col items-center gap-1 py-3 text-[11px] font-medium transition-colors",
                active ? "text-[#00B0F0]" : "text-gray-500"
              )}
            >
              <Icon size={20} />
              {label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
