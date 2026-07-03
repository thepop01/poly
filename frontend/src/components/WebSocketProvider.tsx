'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { wsClient } from '@/utils/websocket';

interface WebSocketContextType {
  isConnected: boolean;
  subscribe: (listener: (event: any) => void) => () => void;
}

const WebSocketContext = createContext<WebSocketContextType>({
  isConnected: false,
  subscribe: () => () => {},
});

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    wsClient.connect();
    setIsConnected(true);

    return () => {
      // Don't disconnect on unmount — Sidebar may still use wsClient
    };
  }, []);

  return (
    <WebSocketContext.Provider value={{ isConnected, subscribe: (l) => wsClient.subscribe(l) }}>
      {children}
    </WebSocketContext.Provider>
  );
}

export function useGlobalWebSocket() {
  return useContext(WebSocketContext);
}
