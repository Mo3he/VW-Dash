"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BatteryCharging, Car, MapPin, Settings } from "lucide-react";
import clsx from "clsx";

const links = [
  { href: "/", label: "Status", Icon: Car },
  { href: "/charging", label: "Charging", Icon: BatteryCharging },
  { href: "/trips", label: "Trips", Icon: MapPin },
  { href: "/settings", label: "Settings", Icon: Settings },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <>
      {/* Top bar */}
      <header className="sticky top-0 z-10 bg-[#001E50] px-4 py-3 flex items-center gap-3">
        <span className="text-white font-bold tracking-wide text-lg">VW Dash</span>
        <span className="text-[#00B0F0] text-xs font-medium ml-auto">ID.4</span>
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
