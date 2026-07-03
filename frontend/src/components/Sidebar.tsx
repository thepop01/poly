"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Bell } from "lucide-react";
import {
  Zap,
  Trophy,
  Anchor,
} from "lucide-react";
import { wsClient } from "@/utils/websocket";
import { useAuth } from "./AuthProvider";
import { useAccount, useConnect, useDisconnect } from "wagmi";

const navItems = [
  { name: "Alpha Trades", path: "/alpha-calls", icon: Zap },
  { name: "Leaderboard", path: "/leaderboard", icon: Trophy },
  { name: "Wallet Tracker", path: "/tools/wallet-tracker", icon: Anchor },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { token, logout } = useAuth();
  const { address, isConnected } = useAccount();
  const { connect, connectors } = useConnect();
  const { disconnect } = useDisconnect();
  const [notifications, setNotifications] = useState<any[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    wsClient.connect();

    const unsubscribe = wsClient.subscribe((event) => {
      if (event.type === 'new_trade') {
        setNotifications(prev => [event, ...prev].slice(0, 50));
        setUnreadCount(prev => prev + 1);
      }
    });

    return () => {
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const toggleDropdown = () => {
    setShowDropdown(!showDropdown);
    if (!showDropdown) {
      setUnreadCount(0);
    }
  };

  const handleNotificationClick = (walletAddress: string) => {
    setShowDropdown(false);
    router.push(`/wallet/${walletAddress}`);
  };

  return (
    <aside className="w-48 flex-shrink-0 flex flex-col border-r border-border bg-surface overflow-y-auto">
      {/* Logo */}
      <Link
        href="/"
        className="h-16 px-5 flex items-center gap-2 border-b border-border hover:opacity-80 transition-opacity"
      >
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary to-accent flex items-center justify-center flex-shrink-0">
          <span className="text-surface font-black text-xs">P</span>
        </div>
        <span className="text-foreground font-bold tracking-tight">
          Poly<span className="text-primary">Tracker</span>
        </span>
      </Link>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-0.5">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive =
            item.path === "/"
              ? pathname === "/"
              : pathname.startsWith(item.path);

          return (
            <Link
              key={item.path}
              href={item.path}
              className={`group flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 cursor-pointer ${isActive
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-muted-fg hover:text-foreground hover:bg-surface-2 border border-transparent"
                }`}
            >
              <Icon
                size={16}
                strokeWidth={isActive ? 2.5 : 2}
                className={`flex-shrink-0 transition-colors ${isActive ? "text-primary" : "text-muted-fg group-hover:text-foreground"
                  }`}
              />
              <span>{item.name}</span>
              {isActive && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-primary" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer: Notifications + Auth + Status */}
      <div className="p-3 border-t border-border bg-surface-2/30 space-y-2">
        {/* Notifications Bell */}
        <div className="relative" ref={dropdownRef}>
          <button 
            onClick={toggleDropdown}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-muted-fg hover:text-foreground hover:bg-surface-2 transition-all duration-150 cursor-pointer"
          >
            <div className="relative">
              <Bell size={14} strokeWidth={2} />
              {unreadCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-danger rounded-full border-2 border-surface animate-pulse" />
              )}
            </div>
            <span className="text-xs font-medium">Alerts</span>
            {unreadCount > 0 && (
              <span className="ml-auto text-[10px] font-bold bg-danger/10 text-danger px-1.5 py-0.5 rounded-full">{unreadCount}</span>
            )}
          </button>

          {showDropdown && (
            <div className="fixed bottom-4 left-52 w-72 max-h-80 overflow-y-auto bg-surface border border-border-2 rounded-xl shadow-2xl z-50">
              <div className="p-2 border-b border-border flex justify-between items-center bg-surface-2/50">
                <h3 className="text-xs font-semibold text-foreground">Recent Alerts</h3>
                {notifications.length > 0 && (
                  <button 
                    onClick={() => setNotifications([])}
                    className="text-[10px] text-muted-fg hover:text-foreground transition-colors"
                  >
                    Clear
                  </button>
                )}
              </div>
              
              <div className="flex flex-col">
                {notifications.length === 0 ? (
                  <div className="p-4 text-center text-xs text-muted-fg">
                    No alerts yet. Whales will appear here.
                  </div>
                ) : (
                  notifications.map((notif, idx) => (
                    <button
                      key={notif.trade_id || idx}
                      onClick={() => handleNotificationClick(notif.wallet_address)}
                      className="p-2 text-left border-b border-border hover:bg-surface-2 transition-colors group"
                    >
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[10px] font-mono text-[#0EA5E9] truncate max-w-20">
                          {notif.wallet_address?.substring(0, 6)}...{notif.wallet_address?.substring(38)}
                        </span>
                        <span className="text-[9px] text-subtle">
                          {notif.timestamp ? new Date(notif.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                        </span>
                      </div>
                      <div className="text-xs text-foreground font-medium truncate mb-0.5">
                        {notif.market_title}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className={`text-[9px] px-1 py-0.5 rounded font-bold ${notif.side === 'BUY' ? 'text-success bg-success/10' : 'text-danger bg-danger/10'}`}>
                          {notif.side}
                        </span>
                        <span className="text-[9px] text-muted-fg">
                          ${(notif.size || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} at {notif.price?.toFixed(2)}¢
                        </span>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {/* Wallet & Auth */}
        <div className="space-y-2">
          {/* Wallet Connect */}
          {isConnected ? (
            <button
              onClick={() => disconnect()}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg bg-surface-2 border border-border text-foreground hover:bg-surface-3 transition-colors text-xs font-medium cursor-pointer"
            >
              <div className="w-3.5 h-3.5 rounded-full bg-gradient-to-br from-primary to-accent flex-shrink-0" />
              <span className="truncate font-mono">
                {address ? `${address.slice(0, 6)}...${address.slice(-4)}` : "Connected"}
              </span>
            </button>
          ) : (
            <button
              onClick={() => connect({ connector: connectors[0] })}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg bg-primary hover:bg-primary/80 text-surface font-semibold transition-colors duration-150 cursor-pointer text-xs"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20 12H4M12 4v16" />
              </svg>
              <span>Connect Wallet</span>
            </button>
          )}

          {/* Discord Login / Logout */}
          {token ? (
            <button
              onClick={logout}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg bg-surface-2 border border-border text-muted-fg hover:text-foreground hover:bg-surface-3 transition-colors text-xs font-medium cursor-pointer"
            >
              <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z" />
              </svg>
              <span className="truncate">Logout</span>
            </button>
          ) : (
            <button
              onClick={() => {
                window.location.href = "http://localhost:8000/api/discord/login";
              }}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg bg-[#5865F2] hover:bg-[#4752C4] text-white text-xs font-medium transition-colors duration-150 cursor-pointer"
            >
              <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z" />
              </svg>
              Login with Discord
            </button>
          )}
        </div>

        {/* Status */}
        <div className="flex items-center gap-1.5 pt-1.5 border-t border-border/50">
          <div className="w-1.5 h-1.5 rounded-full bg-success shadow-[0_0_6px_rgba(34,197,94,0.6)]" />
          <span className="text-[10px] text-success font-medium">Feed Live</span>
        </div>
      </div>
    </aside>
  );
}
