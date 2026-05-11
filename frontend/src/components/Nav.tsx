"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { BatteryCharging, Car, MapPin, Settings, Route, LogOut, Sun, Moon } from "lucide-react";
import clsx from "clsx";
import { useVehicleName } from "@/app/SettingsProvider";
import { authHeaders, clearAuth, getUsername } from "@/lib/auth";
import { useTheme, useToggleTheme } from "@/components/ThemeProvider";

const links = [
  { href: "/", label: "Status", Icon: Car },
  { href: "/charging", label: "Charging", Icon: BatteryCharging },
  { href: "/trips", label: "Trips", Icon: MapPin },
  { href: "/journeys", label: "Journeys", Icon: Route },
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
            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2C6.477 2 2 6.477 2 12c0 4.418 2.865 8.166 6.839 9.489.5.092.682-.217.682-.482 0-.237-.009-.868-.013-1.703-2.782.604-3.369-1.342-3.369-1.342-.454-1.155-1.11-1.463-1.11-1.463-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.269 2.75 1.025A9.578 9.578 0 0 1 12 6.836a9.59 9.59 0 0 1 2.504.337c1.909-1.294 2.747-1.025 2.747-1.025.546 1.377.202 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.578.688.48C19.138 20.163 22 16.418 22 12c0-5.523-4.477-10-10-10z"/>
            </svg>
          </a>
          <a
            href="https://buymeacoffee.com/Mo3he"
            target="_blank"
            rel="noopener noreferrer"
            title="Buy me a coffee"
            className="p-1.5 rounded-lg text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors"
          >
            <img
              src="https://cdn.buymeacoffee.com/buttons/bmc-new-btn-logo.svg"
              alt="Buy me a coffee"
              width="15"
              height="15"
              style={{ display: "block" }}
            />
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
