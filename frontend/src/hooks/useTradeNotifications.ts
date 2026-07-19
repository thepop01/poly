"use client";

import { useEffect, useState } from "react";
import { wsClient } from "@/utils/websocket";

export interface TradeNotification {
  trade_id?: string;
  wallet_address?: string;
  market_title?: string;
  side?: "BUY" | "SELL";
  size?: number;
  price?: number;
  timestamp?: string;
}

/** Live whale-trade notifications from the websocket feed (max 50 kept). */
export function useTradeNotifications() {
  const [notifications, setNotifications] = useState<TradeNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);

  useEffect(() => {
    wsClient.connect();
    const unsubscribe = wsClient.subscribe((event: any) => {
      if (event.type === "new_trade") {
        setNotifications((prev) => [event, ...prev].slice(0, 50));
        setUnreadCount((prev) => prev + 1);
      }
    });
    return unsubscribe;
  }, []);

  return {
    notifications,
    unreadCount,
    markRead: () => setUnreadCount(0),
    clear: () => setNotifications([]),
  };
}
