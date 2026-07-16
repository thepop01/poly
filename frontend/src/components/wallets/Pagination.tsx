"use client";

import { useEffect, useState } from "react";

export function Pagination({
  page,
  totalPages,
  totalCount,
  onPageChange,
  unitLabel = "wallets",
}: {
  page: number;
  totalPages: number;
  totalCount: number;
  onPageChange: (page: number) => void;
  unitLabel?: string;
}) {
  const [pageInput, setPageInput] = useState(page.toString());

  useEffect(() => {
    setPageInput(page.toString());
  }, [page]);

  const commitInput = () => {
    const val = parseInt(pageInput);
    if (!isNaN(val) && val >= 1 && val <= totalPages) {
      onPageChange(val);
    } else {
      setPageInput(page.toString());
    }
  };

  return (
    <div className="flex items-center justify-between px-4 py-2.5 border-t border-border flex-shrink-0 bg-surface">
      <span className="text-xs text-muted-fg">
        Page {page} of {totalPages} · {totalCount.toLocaleString()} {unitLabel}
      </span>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-fg">Go to:</span>
          <input
            type="number"
            min={1}
            max={totalPages}
            value={pageInput}
            onChange={(e) => setPageInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitInput();
            }}
            onBlur={commitInput}
            className="w-16 px-1.5 py-1 text-xs bg-background border border-border rounded text-center text-foreground outline-none focus:border-primary/50"
          />
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page === 1}
            className="px-3 py-1 text-xs rounded border border-border hover:bg-surface-2 disabled:opacity-40 transition-colors"
          >
            Prev
          </button>
          <button
            onClick={() => onPageChange(Math.min(totalPages, page + 1))}
            disabled={page >= totalPages}
            className="px-3 py-1 text-xs rounded border border-border hover:bg-surface-2 disabled:opacity-40 transition-colors"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
