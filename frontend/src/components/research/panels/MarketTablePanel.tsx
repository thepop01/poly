"use client";

import type { ResearchPanel } from "@/types/research";
import { Pager, PanelEmpty, PanelLoading, fmtMoney, fmtPct, usePanelMembers } from "./panelUtils";

export default function MarketTablePanel({ panel }: { panel: ResearchPanel }) {
  const { members, total, offset, goPage, loading } = usePanelMembers(panel);
  if (loading) return <PanelLoading label="markets" />;
  if (members.length === 0) return <PanelEmpty label="markets" />;
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Market</th>
              <th>Category</th>
              <th>Wallets</th>
              <th>Open/Closed</th>
              <th>Outcomes</th>
              <th>Total value</th>
              <th>Coverage</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => {
              const p = m.payload as Record<string, unknown>;
              const path = [p.category, p.subcategory, p.league].filter(Boolean).join(" → ");
              return (
                <tr key={`${m.ordinal}-${m.entity_key}`}>
                  <td className="max-w-64">
                    <span className="font-medium">{String(p.title ?? m.entity_key)}</span>
                  </td>
                  <td className="text-xs">{path || "—"}</td>
                  <td className="font-mono">{String(p.wallet_count ?? "—")}</td>
                  <td className="font-mono">
                    {String(p.open_wallets ?? "—")}/{String(p.closed_wallets ?? "—")}
                  </td>
                  <td className="text-xs">
                    {Array.isArray(p.outcomes) ? p.outcomes.join(", ") : "—"}
                  </td>
                  <td className="font-mono">{fmtMoney(p.total_value)}</td>
                  <td className="font-mono">{fmtPct(p.coverage_pct)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Pager offset={offset} total={total} onPage={goPage} />
    </div>
  );
}
