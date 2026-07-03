import { getAuthToken } from './api';

type TradeAlert = {
  type: 'new_trade';
  trade_id: string;
  wallet_address: string;
  market_id: string;
  market_title: string;
  side: 'BUY' | 'SELL';
  price: number;
  size: number;
  tier: string | null;
  strategy: string | null;
  timestamp: string;
};

type PriceTick = {
  type: 'price_tick';
  market_id: string;
  price: number;
};

type WSEvent = TradeAlert | PriceTick;

type Listener = (event: WSEvent) => void;

class WebSocketClient {
  private ws: WebSocket | null = null;
  private listeners: Set<Listener> = new Set();
  private reconnectTimer: NodeJS.Timeout | null = null;
  private isConnecting = false;

  connect() {
    if (this.ws || this.isConnecting) return;
    
    const token = getAuthToken();
    if (!token) return; // Cannot connect without auth

    this.isConnecting = true;
    
    // Use wss:// in production, ws:// locally
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = process.env.NEXT_PUBLIC_API_URL 
      ? process.env.NEXT_PUBLIC_API_URL.replace(/^https?:\/\//, '')
      : '127.0.0.1:8000';
      
    const url = `${protocol}//${host}/api/ws?token=${token}`;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log('[WebSocket] Connected');
      this.isConnecting = false;
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const data: WSEvent = JSON.parse(event.data);
        this.listeners.forEach(listener => listener(data));
      } catch (e) {
        console.error('[WebSocket] Failed to parse message', e);
      }
    };

    this.ws.onclose = () => {
      console.log('[WebSocket] Disconnected. Reconnecting in 5s...');
      this.ws = null;
      this.isConnecting = false;
      this.scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error('[WebSocket] Error', err);
      // onclose will fire right after this usually
    };
  }

  private scheduleReconnect() {
    if (!this.reconnectTimer) {
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this.connect();
      }, 5000);
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  subscribe(listener: Listener) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}

// Singleton instance
export const wsClient = new WebSocketClient();
