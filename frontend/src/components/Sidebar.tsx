"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Zap,
  Anchor,
  Globe,
  Star,
  UserPlus,
  Bot,
  Terminal,
  LayoutDashboard,
  LogOut,
} from "lucide-react";
import { useAuth } from "./AuthProvider";
import { useShell } from "./ShellProvider";
import { useAccount, useConnect, useDisconnect } from "wagmi";
import { Avatar } from "./ui/Avatar";

interface NavItem {
  name: string;
  path: string;
  icon: React.ComponentType<{ size?: number | string; strokeWidth?: number | string; className?: string }>;
  exact?: boolean;
}

const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "Discovery",
    items: [
      { name: "Wallets", path: "/wallets", icon: Globe, exact: true },
      { name: "Feed", path: "/feed", icon: Zap },
      { name: "Research Hub", path: "/hub", icon: Terminal },
    ],
  },
  {
    title: "User Hub",
    items: [
      { name: "Overview", path: "/dashboard", icon: LayoutDashboard },
      { name: "My Tracker", path: "/tracker", icon: Anchor },
      { name: "Agents", path: "/agents", icon: Bot },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { token, user, logout } = useAuth();
  const { collapsed } = useShell();
  const { address, isConnected } = useAccount();
  const { connect, connectors } = useConnect();
  const { disconnect } = useDisconnect();

  const isActive = (item: NavItem) =>
    item.exact ? pathname === item.path : pathname.startsWith(item.path);

  return (
    <aside
      className={`${
        collapsed ? "w-14" : "w-52"
      } flex-shrink-0 flex flex-col border-r border-border bg-surface overflow-y-auto overflow-x-hidden transition-[width] duration-200`}
    >
      {/* Logo */}
      <Link
        href="/"
        className={`h-16 flex items-center gap-2.5 border-b border-border hover:opacity-80 transition-opacity flex-shrink-0 ${
          collapsed ? "justify-center px-0" : "px-4"
        }`}
      >
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center flex-shrink-0 shadow-sm">
          <span className="text-white font-black text-sm">P</span>
        </div>
        {!collapsed && (
          <div className="leading-tight min-w-0">
            <div className="text-foreground font-bold tracking-tight text-sm">
              PolyTracker
            </div>
            <div className="text-[10px] text-subtle truncate">
              Smart money tracker
            </div>
          </div>
        )}
      </Link>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-5">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title}>
            {!collapsed && (
              <div className="px-3 mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-subtle">
                {section.title}
              </div>
            )}
            <div className="space-y-0.5">
              {section.items.map((item) => {
                const Icon = item.icon;
                const active = isActive(item);
                return (
                  <Link
                    key={item.path}
                    href={item.path}
                    title={collapsed ? item.name : undefined}
                    className={`group flex items-center gap-3 rounded-lg text-sm font-medium transition-colors duration-150 cursor-pointer ${
                      collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2"
                    } ${
                      active
                        ? "bg-primary/10 text-primary font-semibold border border-primary/20"
                        : "text-muted-fg hover:text-foreground hover:bg-surface-2"
                    }`}
                  >
                    <Icon
                      size={16}
                      strokeWidth={active ? 2.5 : 2}
                      className={`flex-shrink-0 transition-colors ${
                        active
                          ? "text-primary"
                          : "text-subtle group-hover:text-foreground"
                      }`}
                    />
                    {!collapsed && <span className="truncate">{item.name}</span>}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer: identity + wallet + status */}
      <div className={`border-t border-border bg-surface-2/30 flex-shrink-0 ${collapsed ? "p-2" : "p-3"} space-y-2`}>
        {/* Wallet connect */}
        {isConnected ? (
          <button
            onClick={() => disconnect()}
            title="Disconnect wallet"
            className={`w-full flex items-center gap-2 rounded-lg bg-surface-2 border border-border text-foreground hover:bg-surface-3 transition-colors text-xs font-medium cursor-pointer ${
              collapsed ? "justify-center p-2" : "px-2 py-1.5"
            }`}
          >
            <div className="w-3.5 h-3.5 rounded-full bg-primary flex-shrink-0" />
            {!collapsed && (
              <span className="truncate font-mono">
                {address ? `${address.slice(0, 6)}...${address.slice(-4)}` : "Connected"}
              </span>
            )}
          </button>
        ) : (
          <button
            onClick={() => connect({ connector: connectors[0] })}
            title="Connect wallet"
            className={`w-full flex items-center gap-2 rounded-lg bg-primary hover:bg-primary/90 text-white font-semibold transition-colors duration-150 cursor-pointer text-xs shadow-sm ${
              collapsed ? "justify-center p-2" : "px-2 py-1.5"
            }`}
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M20 12H4M12 4v16" />
            </svg>
            {!collapsed && <span>Connect Wallet</span>}
          </button>
        )}

        {/* User identity */}
        {token && user && !user.isGuest ? (
          <div className={`flex items-center gap-2 ${collapsed ? "justify-center" : ""}`}>
            <Avatar name={user?.username || "U"} address={user?.id} size={26} />
            {!collapsed && (
              <>
                <div className="min-w-0 flex-1 leading-tight">
                  <div className="text-xs font-medium text-foreground truncate">
                    {user?.username || "Logged in"}
                  </div>
                  <div className="text-[10px] text-subtle truncate">Discord</div>
                </div>
                <button
                  onClick={logout}
                  title="Logout"
                  className="p-1.5 rounded text-subtle hover:text-danger hover:bg-surface-2 transition-colors cursor-pointer"
                >
                  <LogOut size={13} />
                </button>
              </>
            )}
          </div>
        ) : (
          <button
            onClick={() => {
              const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
              window.location.href = `${apiBase}/api/discord/login`;
            }}
            title="Login with Discord"
            className={`w-full flex items-center gap-2 rounded-lg bg-[#5865F2] hover:bg-[#4752C4] text-white text-xs font-medium transition-colors duration-150 cursor-pointer ${
              collapsed ? "justify-center p-2" : "px-2 py-1.5"
            }`}
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
              <path d="M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z" />
            </svg>
            {!collapsed && "Login with Discord"}
          </button>
        )}
      </div>
    </aside>
  );
}
