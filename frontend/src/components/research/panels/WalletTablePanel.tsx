"use client";

import type { ResearchPanel } from "@/types/research";
import { Pager, PanelEmpty, PanelLoading, fmtMoney, fmtPct, usePanelMembers } from "./panelUtils";

export default function WalletTablePanel({ panel }: { panel: ResearchPanel }) {
  const { members, total, offset, goPage, loading } = usePanelMembers(panel);
  if (loading) return <PanelLoading label="wallets" />;
  if (members.length === 0) {
    const summary = (panel.config.summary ?? {}) as {
      available_scopes?: { subcategory: string; league: string; wallets: number }[];
    };
    const scopes = summary.available_scopes ?? [];
    return (
      <PanelEmpty
        label="wallets"
        hint={
          scopes.length > 0 ? (
            <div className="mx-auto mt-3 max-w-sm rounded-lg border border-border bg-surface-2/50 p-3 text-left">
              <p className="text-xs font-semibold text-foreground">
                That scope matches nothing stored. Nearby scopes:
              </p>
              <ul className="mt-1 space-y-0.5 text-xs text-muted-fg">
                {scopes.map((scope) => (
                  <li key={`${scope.subcategory}|${scope.league}`} className="font-mono">
                    {scope.subcategory || "Unclassified"}
                    {scope.league ? ` → ${scope.league}` : ""} ·{" "}
                    {scope.wallets.toLocaleString()} wallets
                  </li>
                ))}
              </ul>
            </div>
          ) : undefined
        }
      />
    );
  }
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Wallet</th>
              <th>Win rate</th>
              <th>W-L</th>
              <th>PnL</th>
              <th>Volume</th>
              <th>Balance</th>
              <th>Open value</th>
              <th>Last active</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => {
              const p = m.payload as Record<string, unknown>;
              const address = String(p.address ?? m.entity_key);
              const resolved = Number(p.resolved_count ?? 0);
              const wins = Number(p.winning_count ?? 0);
              return (
                <tr key={`${m.ordinal}-${m.entity_key}`}>
                  <td>
                    <a
                      href={`/wallet/${address}`}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-primary hover:underline"
                    >
                      {String(p.username ?? address).slice(0, 18)}
                    </a>
                    <div className="font-mono text-[11px] text-subtle">
                      {address.slice(0, 10)}…{address.slice(-6)}
                    </div>
                  </td>
                  <td className="font-mono">{fmtPct(p.win_rate)}</td>
                  <td className="font-mono">
                    {wins}-{resolved - wins} <span className="text-subtle">({resolved})</span>
                  </td>
                  <td className="font-mono">{fmtMoney(p.pnl)}</td>
                  <td className="font-mono">{fmtMoney(p.volume)}</td>
                  <td className="font-mono">{fmtMoney(p.balance)}</td>
                  <td className="font-mono">{fmtMoney(p.position_value)}</td>
                  <td className="text-xs">
                    {p.last_trade_at ? new Date(String(p.last_trade_at)).toLocaleDateString() : "—"}
                  </td>
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
