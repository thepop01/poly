"use client";

import { useEffect, useState } from "react";
import type { ResearchPanel, ResultMember } from "@/types/research";
import { getResultPage } from "@/utils/researchApi";

export const PANEL_PAGE_SIZE = 100;

export function fmtMoney(value: unknown): string {
  if (typeof value !== "number") return "—";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function fmtPct(value: unknown): string {
  return typeof value === "number" ? `${value.toFixed(1)}%` : "—";
}

export function usePanelMembers(panel: ResearchPanel) {
  // Paging offset resets via the React `key` on each panel component (keyed
  // by result_set_id in PanelRenderer), so no reset effect is needed here.
  const [members, setMembers] = useState<ResultMember[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(() => panel.result_set_id != null);
  const resultSetId = panel.result_set_id;

  useEffect(() => {
    if (!resultSetId) return;
    let cancelled = false;
    getResultPage(resultSetId, offset, PANEL_PAGE_SIZE)
      .then((page) => {
        if (cancelled) return;
        setMembers(page.members);
        setTotal(page.summary.row_count);
      })
      .catch(() => {
        if (!cancelled) {
          setMembers([]);
          setTotal(0);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [resultSetId, offset]);

  const goPage = (next: number) => {
    setLoading(true);
    setOffset(next);
  };

  return { members, total, offset, goPage, loading };
}

export function Pager({
  offset,
  total,
  onPage,
}: {
  offset: number;
  total: number;
  onPage: (offset: number) => void;
}) {
  if (total <= PANEL_PAGE_SIZE) return null;
  const page = Math.floor(offset / PANEL_PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PANEL_PAGE_SIZE));
  return (
    <div className="flex items-center justify-end gap-2 px-3 py-2 text-xs text-subtle">
      <span>
        Page {page} of {pages}
      </span>
      <button
        type="button"
        disabled={offset === 0}
        onClick={() => onPage(Math.max(0, offset - PANEL_PAGE_SIZE))}
        className="rounded border border-border px-2 py-0.5 disabled:opacity-40"
      >
        Prev
      </button>
      <button
        type="button"
        disabled={offset + PANEL_PAGE_SIZE >= total}
        onClick={() => onPage(offset + PANEL_PAGE_SIZE)}
        className="rounded border border-border px-2 py-0.5 disabled:opacity-40"
      >
        Next
      </button>
    </div>
  );
}

export function PanelEmpty({ label, hint }: { label: string; hint?: React.ReactNode }) {
  return (
    <div className="px-3 py-6 text-center">
      <p className="text-sm text-subtle">No {label} in this snapshot.</p>
      {hint}
    </div>
  );
}

export function PanelLoading({ label }: { label: string }) {
  return <p className="px-3 py-6 text-center text-sm text-subtle">Loading {label}…</p>;
}
