"use client";
import { useEffect, useRef, useState } from "react";
import type { WsMessage } from "@/lib/types";

export function useVehicleLive() {
  const [data, setData] = useState<WsMessage | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${protocol}://${window.location.host}/ws`;

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
