"use client";

import type { ResearchPanel, ResultMember } from "@/types/research";
import { Pager, PanelEmpty, PanelLoading, fmtMoney, fmtPct, usePanelMembers } from "./panelUtils";

export default function ConsensusPanel({ panel }: { panel: ResearchPanel }) {
  const { members, total, offset, goPage, loading } = usePanelMembers(panel);
  if (loading) return <PanelLoading label="consensus" />;
  if (members.length === 0) return <PanelEmpty label="consensus rows" />;
  const byMarket = new Map<string, { title: string; rows: ResultMember[] }>();
  for (const m of members) {
    const p = m.payload as Record<string, unknown>;
    const key = String(p.condition_id ?? m.entity_key);
    const group = byMarket.get(key) ?? { title: String(p.title ?? key), rows: [] };
    group.rows.push(m);
    byMarket.set(key, group);
  }
  return (
    <div className="flex flex-col gap-3 p-3">
      {Array.from(byMarket.entries()).map(([key, group]) => (
        <div key={key} className="rounded-lg border border-border">
          <div className="border-b border-border bg-surface-2/50 px-3 py-1.5 text-sm font-semibold">
            {group.title}
          </div>
          {group.rows.map((m) => {
            const p = m.payload as Record<string, unknown>;
            return (
              <div
                key={`${m.ordinal}-${m.entity_key}`}
                className="flex items-center justify-between gap-2 px-3 py-1.5 text-sm"
              >
                <span className="badge badge-outline">{String(p.outcome ?? "?")}</span>
                <span className="font-mono text-xs">
                  {String(p.wallet_count ?? 0)} wallets ({fmtPct(p.wallet_pct)})
                </span>
                <span className="font-mono text-xs">{fmtMoney(p.current_value)}</span>
              </div>
            );
          })}
        </div>
      ))}
      <Pager offset={offset} total={total} onPage={goPage} />
    </div>
  );
}
