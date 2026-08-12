"use client";

import React from "react";

export interface WalletRow {
  address: string;
  username?: string | null;
  tier: string;
  is_dormant: boolean;
  sources?: string[] | null;
  pnl?: string | number | null;
  volume?: string | number | null;
  roi_pct?: string | number | null;
  win_rate?: string | number | null;
  balance?: string | number | null;
  position_value?: string | number | null;
  deposits?: string | number | null;
  withdrawals?: string | number | null;
  last_trade_at?: string | null;
  added_at?: string | null;
  categories?: string[] | null;
  resolved_count?: string | number | null;
  winning_count?: string | number | null;
  avg_buy_price?: string | number | null;
  buys_below_15c?: string | number | null;
  wins_below_15c?: string | number | null;
  buys_15_30c?: string | number | null;
  wins_15_30c?: string | number | null;
  buys_30_45c?: string | number | null;
  wins_30_45c?: string | number | null;
  buys_45_60c?: string | number | null;
  wins_45_60c?: string | number | null;
  buys_60_75c?: string | number | null;
  wins_60_75c?: string | number | null;
  buys_above_75c?: string | number | null;
  wins_above_75c?: string | number | null;
  favorite_count?: string | number | null;
}

export interface ColumnDef {
  key: string;
  label: React.ReactNode;
  sortable?: boolean;
  align?: "left" | "right" | "center";
  render: (w: WalletRow, index: number) => React.ReactNode;
}

export function WalletTable({
  columns,
  rows,
  loading,
  sortField,
  sortOrder,
  onSort,
  emptyMessage,
  rowOffset = 0,
}: {
  columns: ColumnDef[];
  rows: WalletRow[];
  loading: boolean;
  sortField: string;
  sortOrder: "asc" | "desc";
  onSort: (key: string) => void;
  emptyMessage: string;
  rowOffset?: number;
}) {
  return (
    <div className="overflow-x-auto overflow-y-auto flex-1">
      <table className="w-full text-left text-sm border-collapse min-w-[1000px]">
        <thead className="sticky top-0 z-10">
          <tr className="border-b border-border bg-surface text-muted-fg font-mono uppercase tracking-wider text-xs">
            <th className="py-2.5 px-4 font-semibold w-12 text-center">#</th>
            {columns.map((col) => (
              <th
                key={col.key}
                className={`py-2.5 px-3 font-semibold select-none ${
                  col.align === "left" ? "text-left" : col.align === "center" ? "text-center" : "text-right"
                } ${col.sortable ? "cursor-pointer hover:text-foreground transition-colors" : ""}`}
                onClick={() => col.sortable && onSort(col.key)}
              >
                <div className={`flex items-center gap-1 ${col.align === "left" ? "justify-start" : col.align === "center" ? "justify-center" : "justify-end"}`}>
                  {col.label}
                  {col.sortable && sortField === col.key && (sortOrder === "desc" ? "↓" : "↑")}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={1 + columns.length} className="py-12 text-center text-muted-fg">
                <div className="flex flex-col items-center gap-2">
                  <div className="w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
                  Loading wallets...
                </div>
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td colSpan={1 + columns.length} className="py-12 text-center text-muted-fg">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr key={row.address} className="border-b border-border hover:bg-surface-2/40 transition-colors">
                <td className="py-3.5 px-4 text-center font-medium text-muted-fg text-xs">
                  {rowOffset + i + 1}
                </td>
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={`py-3.5 px-3 font-mono text-xs ${col.align === "left" ? "text-left" : col.align === "center" ? "text-center" : "text-right"}`}
                  >
                    {col.render(row, i)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
