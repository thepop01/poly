"use client";

import { Suspense } from "react";
import { usePathname } from "next/navigation";
import { WalletTierTabs } from "./wallets/WalletTierTabs";

const PAGE_TITLES: { prefix: string; title: string; description: string }[] = [
  { prefix: "/dashboard", title: "Dashboard", description: "Your workspace — watchlist, agents, and the live feed" },
  { prefix: "/feed", title: "Feed", description: "Live feed of large trades and deposits caught by the scanners" },
  { prefix: "/wallets", title: "Wallets", description: "Every tracked wallet, ranked by performance" },
  { prefix: "/tracker", title: "My Tracker", description: "Your personal wallet lists" },
  { prefix: "/agents", title: "Agents", description: "Conditional rules that monitor the market for you" },
  { prefix: "/hub", title: "Research Hub", description: "AI-driven market research, wallet intelligence, and mock execution" },
];

export default function HeaderBar() {
  const pathname = usePathname();

  if (pathname.startsWith("/wallet/") || pathname.startsWith("/hub")) {
    return null;
  }

  const page = PAGE_TITLES.find((p) => pathname.startsWith(p.prefix));

  return (
    <header className="h-16 flex-shrink-0 flex items-center gap-4 px-5 border-b border-border bg-background">
      <div className="min-w-0 flex-shrink-0">
        <h1 className="text-base font-bold text-foreground leading-tight truncate">
          {page?.title ?? "PolyTracker"}
        </h1>
        {page?.description && (
          <p className="text-xs text-subtle truncate">{page.description}</p>
        )}
      </div>

      {page?.prefix === "/wallets" && (
        <>
          <div className="h-8 w-px bg-border hidden md:block flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <Suspense fallback={null}>
              <WalletTierTabs />
            </Suspense>
          </div>
        </>
      )}

      {page?.prefix !== "/wallets" && <div className="flex-1" />}
    </header>
  );
}

