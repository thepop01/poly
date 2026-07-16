"use client";

import { useEffect, useRef, useState } from "react";
import { getWalletList, WalletListParams } from "@/utils/api";
import type { WalletRow } from "@/components/wallets/WalletTable";

export function useWalletList(params: WalletListParams) {
  const [wallets, setWallets] = useState<WalletRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refetchTick, setRefetchTick] = useState(0);
  const requestId = useRef(0);

  const { tab, source, search, sort_by, sort_order, limit, offset } = params;

  useEffect(() => {
    const id = ++requestId.current;
    let cancelled = false;
    setLoading(true);
    setError(null);

    // Debounce search keystrokes; fire immediately otherwise
    const delay = search ? 300 : 0;
    const timer = setTimeout(async () => {
      try {
        const res = await getWalletList({ tab, source, search, sort_by, sort_order, limit, offset });
        if (cancelled || id !== requestId.current) return;
        setWallets(res.wallets || []);
        setTotal(res.total_count || 0);
      } catch (e) {
        if (cancelled || id !== requestId.current) return;
        setError(e instanceof Error ? e.message : "Failed to load wallets");
        setWallets([]);
        setTotal(0);
      } finally {
        if (!cancelled && id === requestId.current) setLoading(false);
      }
    }, delay);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [tab, source, search, sort_by, sort_order, limit, offset, refetchTick]);

  return {
    wallets,
    total,
    loading,
    error,
    refetch: () => setRefetchTick((t) => t + 1),
  };
}
