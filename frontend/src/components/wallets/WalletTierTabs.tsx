"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getWalletCounts } from "@/utils/api";
import { PillTabs } from "@/components/ui/PillTabs";

export const ACTIVE_TABS = [
  { key: "all", label: "All" },
  { key: "curated", label: "Curated" },
  { key: "standard", label: "Standard" },
  { key: "low_balance", label: "Low Balance" },
  { key: "new", label: "New" },
] as const;

export const HIBERNATED_TABS = [{ key: "hibernated", label: "Hibernated" }] as const;

export const TABS = [...ACTIVE_TABS, ...HIBERNATED_TABS] as const;

export type TabKey = (typeof TABS)[number]["key"];

export function WalletTierTabs() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tab: TabKey = (TABS.find((t) => t.key === tabParam)?.key as TabKey) || "all";
  const [counts, setCounts] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    getWalletCounts().then(setCounts).catch(() => setCounts(null));
  }, []);

  const tabCount = (key: TabKey) => {
    if (!counts) return null;
    return key === "all" ? counts.all : counts[key];
  };

  const switchTab = (key: TabKey) => {
    router.replace(key === "all" ? "/wallets" : `/wallets?tab=${key}`, { scroll: false });
  };

  return (
    <div className="flex items-center gap-3 min-w-0 overflow-x-auto scrollbar-hide">
      <div className="flex items-center gap-2 flex-shrink-0">
        <span className="text-[11px] font-bold text-subtle uppercase tracking-wider hidden xl:inline">
          Active Category:
        </span>
        <PillTabs
          size="sm"
          tabs={ACTIVE_TABS.map((t) => ({ key: t.key, label: t.label, count: tabCount(t.key) }))}
          active={tab}
          onChange={(k) => switchTab(k as TabKey)}
        />
      </div>
      <div className="h-5 w-px bg-border flex-shrink-0 hidden sm:block" />
      <div className="flex items-center gap-2 flex-shrink-0">
        <span className="text-[11px] font-bold text-subtle uppercase tracking-wider hidden xl:inline">
          Hibernated:
        </span>
        <PillTabs
          size="sm"
          tabs={HIBERNATED_TABS.map((t) => ({ key: t.key, label: t.label, count: tabCount(t.key) }))}
          active={tab}
          onChange={(k) => switchTab(k as TabKey)}
        />
      </div>
    </div>
  );
}
