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

  const handleActionClick = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  return (
    <div className="flex items-center gap-1.5 group">
      {username && username.length <= 20 && (
        <Link
          href={`/wallet/${address}`}
          className="text-muted-fg hover:text-primary text-xs font-semibold truncate max-w-[90px] transition-colors"
          title={username}
        >
          {username}
        </Link>
      )}
      <Link
        href={`/wallet/${address}`}
        className="font-mono bg-primary/5 hover:bg-primary/15 px-2 py-0.5 rounded border border-primary/10 hover:border-primary/30 whitespace-nowrap text-xs text-foreground hover:text-primary transition-all duration-150 cursor-pointer shadow-sm hover:shadow-[0_0_8px_rgba(59,130,246,0.2)]"
        title="View Wallet Profile & Analytics"
      >
        {formatAddress(address)}
      </Link>
      <button
        onClick={(e) => {
          handleActionClick(e);
          onCopy(e, address);
        }}
        className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-foreground transition-colors cursor-pointer"
        title="Copy Address"
      >
        {copiedAddress === address ? <Check size={11} className="text-green-500" /> : <Copy size={11} />}
      </button>
      <a
        href={`https://polymarket.com/profile/${address}`}
        target="_blank"
        rel="noopener noreferrer"
        onClick={handleActionClick}
        className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-primary transition-colors cursor-pointer"
        title="View on Polymarket"
      >
        <Globe size={11} />
      </a>
      <a
        href={`https://activity.polymarket-tools.com/?address=${address}`}
        target="_blank"
        rel="noopener noreferrer"
        onClick={handleActionClick}
        className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-primary transition-colors cursor-pointer"
        title="PolyTools Activity"
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

