"use client";
import { useEffect, useRef, useState } from "react";
import type { ChargeLocation } from "@/lib/types";
import { api } from "@/lib/api";

function ChargeMapInner({ locations }: { locations: ChargeLocation[] }) {
  const id = "charge-map";
  const mapRef = useRef<import("leaflet").Map | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || !locations.length) return;

    import("leaflet").then((L) => {
      const container = document.getElementById(id);
      if (!container) return;

      // Tear down any previous instance before re-initialising
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }

      // Fix default marker icon paths broken by webpack
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });

      const map = L.map(id, { zoomControl: true });
      mapRef.current = map;

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors",
      }).addTo(map);

      const maxKwh = Math.max(...locations.map((l) => l.total_kwh), 1);

      locations.forEach((loc) => {
        const ratio = loc.total_kwh / maxKwh;
        const r = Math.round(8 + ratio * 16);
        const opacity = 0.5 + ratio * 0.5;

        const circle = L.circleMarker([loc.latitude, loc.longitude], {
          radius: r,
          fillColor: "#00B0F0",
          color: "#001E50",
          weight: 1.5,
          opacity: 1,
          fillOpacity: opacity,
        }).addTo(map);

        circle.bindPopup(
          `<strong>${loc.name}</strong><br/>` +
          `${loc.sessions} session${loc.sessions !== 1 ? "s" : ""}<br/>` +
          `${loc.total_kwh} kWh`
        );
      });

      const bounds = L.latLngBounds(locations.map((l) => [l.latitude, l.longitude]));
      map.fitBounds(bounds, { padding: [32, 32] });
    });

    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, [locations]);

  return (
    <div
      id={id}
      style={{ height: 280, borderRadius: "1rem", overflow: "hidden" }}
      className="bg-[#0d1117] w-full"
    />
  );
}

export default function ChargeMap({ start, end }: { start?: string; end?: string }) {
  const [locations, setLocations] = useState<ChargeLocation[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    api.charging.locations(start, end).then((data) => {
      setLocations(data);
      setLoaded(true);
    }).catch(() => setLoaded(true));
    if (!document.getElementById("leaflet-css")) {
      const link = document.createElement("link");
      link.id = "leaflet-css";
      link.rel = "stylesheet";
      link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(link);
    }
  }, [start, end]);

  if (!loaded) {
    return (
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Charge map</div>
        <div className="h-52 flex items-center justify-center text-gray-600 text-sm">
          Loading map…
        </div>
      </div>
    );
  }

  if (!locations.length) {
    return (
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Charge map</div>
        <div className="h-32 flex items-center justify-center text-gray-600 text-sm">
          No location data yet — addresses are geocoded when sessions close
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">
        Charge map <span className="text-gray-600 normal-case">({locations.length} locations)</span>
      </div>
      <ChargeMapInner locations={locations} />
    </div>
  );
}
