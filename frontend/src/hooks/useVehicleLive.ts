"use client";
import { useEffect, useRef, useState } from "react";
import type { WsMessage } from "@/lib/types";

function getWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  // In development Next.js dev server doesn't proxy WebSocket upgrades,
  // so connect directly to the FastAPI backend port.
  if (process.env.NODE_ENV === "development") {
    return `${protocol}://${window.location.hostname}:8000/ws`;
  }
  // In production the proxy-server.js forwards WS upgrades from port 3000 → 8000.
  return `${protocol}://${window.location.host}/ws`;
}

export function useVehicleLive() {
  const [data, setData] = useState<WsMessage | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const url = getWsUrl();

    function connect() {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        // Reconnect after 5s
        setTimeout(connect, 5000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data) as WsMessage;
          setData(msg);
        } catch {
          // ignore malformed frames
        }
      };
    }

    connect();
    return () => {
      wsRef.current?.close();
    };
  }, []);

  return { data, connected };
}
