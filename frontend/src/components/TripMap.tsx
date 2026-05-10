"use client";
import { useEffect, useRef } from "react";

interface Point { lat: number; lon: number }

interface Props {
  points: Point[];
  mapId: string;
}

let cssInjected = false;

export default function TripMap({ points, mapId }: Props) {
  const initialised = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined" || initialised.current || points.length < 2) return;
    initialised.current = true;

    if (!cssInjected) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(link);
      cssInjected = true;
    }

    import("leaflet").then((L) => {
      const container = document.getElementById(mapId) as HTMLElement & { _leaflet_id?: number };
      if (!container || container._leaflet_id) return;

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });

      const map = L.map(mapId);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors",
      }).addTo(map);

      const latlngs = points.map((p) => [p.lat, p.lon] as [number, number]);

      L.polyline(latlngs, { color: "#00B0F0", weight: 3, opacity: 0.85 }).addTo(map);

      // Start marker (green dot)
      L.circleMarker(latlngs[0], {
        radius: 6, fillColor: "#4ade80", color: "#fff", weight: 1.5, fillOpacity: 1,
      }).addTo(map);

      // End marker (red dot)
      L.circleMarker(latlngs[latlngs.length - 1], {
        radius: 6, fillColor: "#ef4444", color: "#fff", weight: 1.5, fillOpacity: 1,
      }).addTo(map);

      map.fitBounds(latlngs, { padding: [16, 16] });
    });
  }, [points, mapId]);

  if (points.length < 2) {
    return (
      <div className="h-32 flex items-center justify-center text-xs text-gray-600">
        No route data available
      </div>
    );
  }

  return (
    <div
      id={mapId}
      style={{ height: 200, borderRadius: "0.75rem", overflow: "hidden" }}
      className="w-full bg-[#0d1117] mt-3"
    />
  );
}
