"use client";
import { useEffect, useRef, useState } from "react";
import type { WsMessage } from "@/lib/types";

function getWsUrl(): string {
  // Explicit override — used in dev when pointing at a non-default backend port
  // e.g. NEXT_PUBLIC_WS_URL=ws://127.0.0.1:8001/ws
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL;
  }
  // Production: proxy-server.js forwards WS upgrades on the same host/port
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
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
