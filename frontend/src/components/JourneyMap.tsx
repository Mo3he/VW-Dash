"use client";
import { useEffect, useRef } from "react";

interface Point { lat: number; lon: number }

interface Props {
  routes: Point[][];  // one array of points per trip
  mapId: string;
}

let cssInjected = false;

export default function JourneyMap({ routes, mapId }: Props) {
  const initialised = useRef(false);

  const allPoints = routes.flat();

  useEffect(() => {
    if (typeof window === "undefined" || initialised.current || allPoints.length < 2) return;
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

      const map = L.map(mapId, { zoomControl: false, attributionControl: false });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map);

      const allLatLngs: [number, number][] = [];

      routes.forEach((pts, i) => {
        if (pts.length < 2) return;
        const latlngs = pts.map((p) => [p.lat, p.lon] as [number, number]);
        allLatLngs.push(...latlngs);

        L.polyline(latlngs, { color: "#00B0F0", weight: 3, opacity: 0.8 }).addTo(map);

        // First trip: green start dot
        if (i === 0) {
          L.circleMarker(latlngs[0], {
            radius: 6, fillColor: "#4ade80", color: "#fff", weight: 1.5, fillOpacity: 1,
          }).addTo(map);
        }

        // Every trip: red end dot (last trip's end = journey end)
        L.circleMarker(latlngs[latlngs.length - 1], {
          radius: 5, fillColor: "#ef4444", color: "#fff", weight: 1.5, fillOpacity: 1,
        }).addTo(map);
      });

      if (allLatLngs.length >= 2) {
        map.fitBounds(allLatLngs, { padding: [16, 16] });
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapId]);

  if (allPoints.length < 2) {
    return (
      <div className="h-32 flex items-center justify-center text-xs text-gray-600">
        No route data available
      </div>
    );
  }

  return (
    <div
      id={mapId}
      style={{ height: 220, borderRadius: "0.75rem", overflow: "hidden" }}
      className="w-full bg-[#0d1117] mt-2"
    />
  );
}
