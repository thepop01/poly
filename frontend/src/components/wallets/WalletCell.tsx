"use client";

import Link from "next/link";
import { Globe, Copy, Check, Info } from "lucide-react";
import { formatAddress } from "@/utils/format";
import type { WatchlistStatus } from "@/hooks/useWatchlistAdd";
import { LikeButton } from "@/components/ui/LikeButton";

export function WalletCell({
  address,
  username,
  copiedAddress,
  onCopy,
  watchlistStatus,
  onAddToWatchlist,
  favoriteCount,
  isLiked,
  onToggleLike,
}: {
  address: string;
  username?: string | null;
  copiedAddress: string | null;
  onCopy: (e: React.MouseEvent, address: string) => void;
  watchlistStatus?: Record<string, WatchlistStatus>;
  onAddToWatchlist?: (e: React.MouseEvent, address: string) => void;
  favoriteCount?: number;
  isLiked?: boolean;
  onToggleLike?: (e: React.MouseEvent, address: string) => void;
}) {
  const isCurrentlyLiked = isLiked || (watchlistStatus && watchlistStatus[address] === "success");

  const handleLike = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (onToggleLike) {
      onToggleLike(e, address);
    } else if (onAddToWatchlist) {
      onAddToWatchlist(e, address);
    }
  };

  return (
    <div className="flex items-center gap-1.5">
      {username && username.length <= 20 && (
        <span className="text-muted-fg text-xs font-semibold truncate max-w-[90px]" title={username}>
          {username}
        </span>
      )}
      <Link
        href={`/wallet/${address}`}
        className="hover:text-primary transition-colors font-mono bg-primary/5 px-2 py-0.5 rounded border border-primary/10 whitespace-nowrap text-xs"
      >
        {formatAddress(address)}
      </Link>
      <button
        onClick={(e) => onCopy(e, address)}
        className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-foreground transition-colors"
        title="Copy"
      >
        {copiedAddress === address ? <Check size={11} className="text-green-500" /> : <Copy size={11} />}
      </button>
      <a
        href={`https://polymarket.com/profile/${address}`}
        target="_blank"
        rel="noopener noreferrer"
        className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-primary transition-colors"
        title="View on Polymarket"
      >
        <Globe size={11} />
      </a>
      <a
        href={`https://activity.polymarket-tools.com/?address=${address}`}
        target="_blank"
        rel="noopener noreferrer"
        className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-primary transition-colors"
        title="PolyTools"
      >
        <Info size={11} />
      </a>

      {/* Like / Favorite Button + Count Chip */}
      <LikeButton
        isLiked={Boolean(isCurrentlyLiked)}
        onToggle={handleLike}
        favoriteCount={favoriteCount}
        size={13}
      />
    </div>
  );
}
