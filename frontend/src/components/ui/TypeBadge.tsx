"use client";

import { ArrowLeftRight, ArrowDownToLine } from "lucide-react";

const STYLES = {
  trade: {
    label: "Trade",
    className: "border-primary/30 text-primary bg-primary/5",
    icon: <ArrowLeftRight size={10} />,
  },
  deposit: {
    label: "Deposit",
    className: "border-sky-500/30 text-sky-400 bg-sky-500/5",
    icon: <ArrowDownToLine size={10} />,
  },
  buy: {
    label: "Buy",
    className: "border-success/30 text-success bg-success/5",
    icon: null,
  },
  sell: {
    label: "Sell",
    className: "border-danger/30 text-danger bg-danger/5",
    icon: null,
  },
} as const;

export type TypeBadgeKind = keyof typeof STYLES;

export function TypeBadge({ kind }: { kind: TypeBadgeKind }) {
  const s = STYLES[kind];
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border font-mono text-[10px] font-bold uppercase tracking-wider whitespace-nowrap ${s.className}`}
    >
      {s.icon}
      {s.label}
    </span>
  );
}
