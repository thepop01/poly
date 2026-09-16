"use client";

import type { ResearchPanel } from "@/types/research";
import { Pager, PanelEmpty, PanelLoading, fmtMoney, fmtPct, usePanelMembers } from "./panelUtils";

export default function OverlapPanel({ panel }: { panel: ResearchPanel }) {
  const { members, total, offset, goPage, loading } = usePanelMembers(panel);
  if (loading) return <PanelLoading label="overlap" />;
  if (members.length === 0) return <PanelEmpty label="shared markets" />;
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Market</th>
              <th>Wallets</th>
              <th>Coverage</th>
              <th>Outcomes</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => {
              const p = m.payload as Record<string, unknown>;
              const outcomes = (p.outcomes ?? {}) as Record<string, number>;
              const exact =
                typeof p.wallet_count === "number" &&
                typeof p.input_wallet_count === "number" &&
                p.wallet_count === p.input_wallet_count;
              return (
                <tr key={`${m.ordinal}-${m.entity_key}`}>
                  <td className="max-w-64">
                    <span className="font-medium">{String(p.title ?? m.entity_key)}</span>
                  </td>
                  <td className="font-mono">{String(p.wallet_count ?? "—")}</td>
                  <td className="font-mono">
                    {fmtPct(p.coverage_pct)}{" "}
                    {exact && <span className="badge badge-success">all</span>}
                  </td>
                  <td className="text-xs">
                    {Object.entries(outcomes)
                      .map(([label, count]) => `${label}: ${count}`)
                      .join(" · ") || "—"}
                  </td>
                  <td className="font-mono">{fmtMoney(p.current_value)}</td>
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
