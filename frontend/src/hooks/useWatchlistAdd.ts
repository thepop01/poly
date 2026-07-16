"use client";

import { useState } from "react";
import { toggleWatchlist } from "@/utils/api";

export type WatchlistStatus = "idle" | "loading" | "success";

export function useWatchlistAdd() {
  const [watchlistStatus, setWatchlistStatus] = useState<Record<string, WatchlistStatus>>({});

  const handleAddToWatchlist = async (e: React.MouseEvent, address: string) => {
    e.preventDefault();
    try {
      setWatchlistStatus((prev) => ({ ...prev, [address]: "loading" }));
      await toggleWatchlist(address, "add");
      setWatchlistStatus((prev) => ({ ...prev, [address]: "success" }));
      setTimeout(() => setWatchlistStatus((prev) => ({ ...prev, [address]: "idle" })), 3000);
    } catch {
      setWatchlistStatus((prev) => ({ ...prev, [address]: "idle" }));
    }
  };

  return { watchlistStatus, handleAddToWatchlist };
}
