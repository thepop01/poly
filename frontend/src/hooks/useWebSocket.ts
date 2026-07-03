import { useEffect, useState, useRef, useCallback } from "react";
import { getAuthToken } from "@/utils/api";

export function useWebSocket() {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<any>(null);
  const ws = useRef<WebSocket | null>(null);
  const reconnectTimeout = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 3;

  const connect = useCallback(() => {
    const token = getAuthToken();
    if (!token) return;

    const baseUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://127.0.0.1:8000/api/ws';
    const url = `${baseUrl}?token=${encodeURIComponent(token)}`;
    ws.current = new WebSocket(url);

    ws.current.onopen = () => {
      setIsConnected(true);
      reconnectAttempts.current = 0;
    };

    ws.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setLastMessage(data);
      } catch (e) {
        console.error("WS Parse error", e);
      }
    };

    ws.current.onclose = () => {
      setIsConnected(false);

      // Auto-reconnect logic
      if (reconnectAttempts.current < maxReconnectAttempts) {
        const timeout = Math.pow(2, reconnectAttempts.current) * 1000;
        reconnectTimeout.current = setTimeout(() => {
          reconnectAttempts.current += 1;
          connect();
        }, timeout);
      } else {
        console.warn("WebSocket: max reconnect attempts reached, giving up.");
      }
    };
  }, []);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current);
      }
      if (ws.current) {
        ws.current.onclose = null;
        ws.current.close();
      }
    };
  }, [connect]);

  return { isConnected, lastMessage };
}

