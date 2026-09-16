"use client";

import { useState, useCallback, useEffect } from "react";
import { toggleWatchlist, getWatchlistStatus } from "@/utils/api";
import { useAuth } from "@/components/AuthProvider";

export function useFavoriteToggle(addresses: string[] = []) {
  const { token } = useAuth();
  const [likedSet, setLikedSet] = useState<Set<string>>(new Set());
  const [loadingAddrs, setLoadingAddrs] = useState<Set<string>>(new Set());

  // Bulk check status for listed addresses on mount or address change
  useEffect(() => {
    if (!token || addresses.length === 0) return;
    let cancelled = false;

    getWatchlistStatus(addresses)
      .then((res) => {
        if (!cancelled && res?.liked) {
          setLikedSet(new Set(res.liked.map((a: string) => a.toLowerCase())));
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [token, addresses.join(",")]);

  const isLiked = useCallback(
    (address: string) => {
      if (!address) return false;
      return likedSet.has(address.toLowerCase());
    },
    [likedSet]
  );

  const toggleLike = useCallback(
    async (address: string, e?: React.MouseEvent) => {
      if (e) {
        e.stopPropagation();
        e.preventDefault();
      }
      if (!address || !token) return;

      const lower = address.toLowerCase();
      const currentlyLiked = likedSet.has(lower);

      // Optimistic update
      setLikedSet((prev) => {
        const next = new Set(prev);
        if (currentlyLiked) {
          next.delete(lower);
        } else {
          next.add(lower);
        }
        return next;
      });

      setLoadingAddrs((prev) => new Set(prev).add(lower));

      try {
        await toggleWatchlist(address, currentlyLiked ? 'remove' : 'add');
      } catch (err) {
        // Rollback on error
        setLikedSet((prev) => {
          const next = new Set(prev);
          if (currentlyLiked) {
            next.add(lower);
          } else {
            next.delete(lower);
          }
          return next;
        });
      } finally {
        setLoadingAddrs((prev) => {
          const next = new Set(prev);
          next.delete(lower);
          return next;
        });
      }
    },
    [token, likedSet]
  );

  return {
    likedSet,
    isLiked,
    toggleLike,
    loadingAddrs,
  };
}
