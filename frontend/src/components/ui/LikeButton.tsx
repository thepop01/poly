"use client";

import React from "react";
import { Heart } from "lucide-react";

export function LikeButton({
  isLiked,
  onToggle,
  favoriteCount,
  size = 15,
  showCount = true,
  disabled = false,
  className = "",
}: {
  isLiked: boolean;
  onToggle: (e: React.MouseEvent) => void;
  favoriteCount?: number;
  size?: number;
  showCount?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      title={isLiked ? "Remove from favorites" : "Add to favorites"}
      className={`inline-flex items-center gap-1.5 px-1.5 py-1 rounded-md transition-all duration-200 group focus:outline-none ${
        isLiked
          ? "text-rose-500 hover:text-rose-400"
          : "text-muted-fg hover:text-rose-400"
      } ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"} ${className}`}
    >
      <Heart
        size={size}
        style={{
          fill: isLiked ? "#f43f5e" : "none",
          stroke: isLiked ? "#f43f5e" : "currentColor",
        }}
        className={`transition-all duration-200 transform ${
          isLiked
            ? "scale-110 group-active:scale-125"
            : "group-hover:scale-110 group-active:scale-90"
        }`}
      />
      {showCount && favoriteCount != null && favoriteCount > 0 && (
        <span className="text-[11px] font-mono font-medium text-rose-400/80 group-hover:text-rose-400">
          {favoriteCount}
        </span>
      )}
    </button>
  );
}
