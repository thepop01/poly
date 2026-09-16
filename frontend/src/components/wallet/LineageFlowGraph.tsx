"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import {
  GitFork,
  ArrowDownLeft,
  ArrowUpRight,
  ExternalLink,
  Layers,
  DollarSign,
  Network,
  ListFilter,
} from "lucide-react";
import { formatCurrency, formatAddress } from "@/utils/format";

/* ── Validated categorical palette (light surface #FFFFFF) ─────────────
   violet #7C3AED · emerald #059669 · blue #2563EB · amber #D97706
   All six checks pass (CVD worst pair ΔE 24.9, normal-vision 27.2). */
const COLORS = {
  parent: "#7C3AED",
  usdIn: "#059669",
  p2pIn: "#2563EB",
  deposit: "#D97706",
  usdOut: "#7C3AED",
  p2pOut: "#2563EB",
};

interface FlowNode {
  key: string;
  label: string;
  sublabel?: string;
  amountLabel: string;
  valueLabel?: string;
  detailDescription?: string;
  txCount?: number;
  tokensCount?: number;
  color: string;
  href?: string | null;
  weight: number; // proportional to edge thickness
}

interface LineageFlowGraphProps {
  address: string;
  username?: string | null;
  tier?: string | null;
  balance?: number;
  positionValue?: number;
  funding?: {
    funding_source?: string;
    funded_by?: string | null;
    funder_username?: string | null;
    funder_tier?: string | null;
    total_funding_received_usd?: number;
    total_funding_sent_usd?: number;
    total_inflows_count?: number;
    total_outflows_count?: number;
    inflows?: Array<any>;
    outflows?: Array<any>;
  } | null;
  positionTransfers?: {
    total_incoming_count?: number;
    total_outgoing_count?: number;
    incoming?: Array<any>;
    outgoing?: Array<any>;
  } | null;
  depositsTotal?: number;
}

export function LineageFlowGraph({
  address,
  username,
  balance = 0,
  positionValue = 0,
  funding,
  positionTransfers,
  depositsTotal = 0,
}: LineageFlowGraphProps) {
  const [viewMode, setViewMode] = useState<"graph" | "ledger">("graph");
  const [ledgerTab, setLedgerTab] = useState<"p2p_in" | "p2p_out" | "usd_in" | "usd_out">("usd_in");
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const incomingP2P = positionTransfers?.incoming || [];
  const outgoingP2P = positionTransfers?.outgoing || [];
  const inflowsUSD = funding?.inflows || [];
  const outflowsUSD = funding?.outflows || [];

  // Group incoming P2P by sender → flow nodes
  const groupedIncomingP2P = useMemo(() => {
    const map = new Map<string, { address: string; username?: string; count: number; totalShares: number; markets: string[]; outcomes: string[] }>();
    for (const t of incomingP2P) {
      const from = t.from_address?.toLowerCase() || "unknown";
      const existing = map.get(from) || { address: from, username: t.from_username, count: 0, totalShares: 0, markets: [] as string[], outcomes: [] as string[] };
      existing.count += 1;
      existing.totalShares += Number(t.amount) || 0;
      const mName = String(t.market_name || "");
      if (mName && !existing.markets.includes(mName) && existing.markets.length < 3) existing.markets.push(mName);
      const oc = String(t.outcome || "");
      if (oc && !existing.outcomes.includes(oc) && existing.outcomes.length < 2) existing.outcomes.push(oc);
      map.set(from, existing);
    }
    return Array.from(map.values()).slice(0, 6);
  }, [incomingP2P]);

  const groupedOutgoingP2P = useMemo(() => {
    const map = new Map<string, { address: string; username?: string; count: number; totalShares: number; markets: string[]; outcomes: string[] }>();
    for (const t of outgoingP2P) {
      const to = t.to_address?.toLowerCase() || "unknown";
      const existing = map.get(to) || { address: to, username: t.to_username, count: 0, totalShares: 0, markets: [] as string[], outcomes: [] as string[] };
      existing.count += 1;
      existing.totalShares += Number(t.amount) || 0;
      const mName = String(t.market_name || "");
      if (mName && !existing.markets.includes(mName) && existing.markets.length < 3) existing.markets.push(mName);
      const oc = String(t.outcome || "");
      if (oc && !existing.outcomes.includes(oc) && existing.outcomes.length < 2) existing.outcomes.push(oc);
      map.set(to, existing);
    }
    return Array.from(map.values()).slice(0, 6);
  }, [outgoingP2P]);

  const groupedInflowsUSD = useMemo(() => {
    const map = new Map<string, { address: string; username?: string; count: number; totalUsd: number }>();
    for (const f of inflowsUSD) {
      const funder = f.funder_address?.toLowerCase() || "unknown";
      const existing = map.get(funder) || { address: funder, username: f.funder_username, count: 0, totalUsd: 0 };
      existing.count += 1;
      existing.totalUsd += Number(f.amount_usd) || 0;
      map.set(funder, existing);
    }
    return Array.from(map.values()).slice(0, 5);
  }, [inflowsUSD]);

  const groupedOutflowsUSD = useMemo(() => {
    const map = new Map<string, { address: string; username?: string; count: number; totalUsd: number }>();
    for (const f of outflowsUSD) {
      const funded = f.funded_address?.toLowerCase() || "unknown";
      const existing = map.get(funded) || { address: funded, username: f.funded_username, count: 0, totalUsd: 0 };
      existing.count += 1;
      existing.totalUsd += Number(f.amount_usd) || 0;
      map.set(funded, existing);
    }
    return Array.from(map.values()).slice(0, 5);
  }, [outflowsUSD]);

  /* ── Build node lists for both sides ──────────────────────────────── */
  const inNodes = useMemo<FlowNode[]>(() => {
    const nodes: FlowNode[] = [];
    if (funding?.funded_by) {
      nodes.push({
        key: `funder-${funding.funded_by}`,
        label: funding.funder_username || formatAddress(funding.funded_by),
        sublabel: "Parent · seed capital & positions",
        amountLabel: formatCurrency(funding.total_funding_received_usd || 0),
        detailDescription: `The parent wallet (${funding.funder_username || formatAddress(funding.funded_by)}) provided initial seed funding & capital lineage.`,
        color: COLORS.parent,
        href: `/wallet/${funding.funded_by}`,
        weight: Math.max(funding.total_funding_received_usd || 0, 1000),
      });
    }
    groupedInflowsUSD.forEach((f) => {
      if (f.address === funding?.funded_by?.toLowerCase()) return; // avoid duplicate of parent
      nodes.push({
        key: `usd-in-${f.address}`,
        label: f.username || formatAddress(f.address),
        sublabel: `${f.count} cash transfer${f.count > 1 ? "s" : ""}`,
        amountLabel: `+${formatCurrency(f.totalUsd)}`,
        detailDescription: `Direct cash transfer of ${formatCurrency(f.totalUsd)} across ${f.count} transaction${f.count > 1 ? "s" : ""}.`,
        color: COLORS.usdIn,
        href: `/wallet/${f.address}`,
        weight: f.totalUsd,
      });
    });
    groupedIncomingP2P.forEach((t) => {
      const outcomeTag = t.outcomes.length > 0 ? ` (${t.outcomes.join("/")})` : "";
      const isParent = funding?.funded_by && t.address.toLowerCase() === funding.funded_by.toLowerCase();
      const senderRole = isParent ? "The parent wallet" : "Sender";
      const totalTokens = Math.round(t.totalShares);
      const estValue = totalTokens * 1.0;
      const desc = `${senderRole} (${t.username || formatAddress(t.address)}) sent a total of ${totalTokens.toLocaleString()} Polymarket outcome shares (contracts) directly into this wallet across ${t.count} separate transaction${t.count > 1 ? "s" : ""}.`;

      nodes.push({
        key: `p2p-in-${t.address}`,
        label: t.username || formatAddress(t.address),
        sublabel: t.markets[0] ? `${t.count}x · ${t.markets[0]}${outcomeTag}` : `${t.count} position transfer${t.count > 1 ? "s" : ""}`,
        amountLabel: `${totalTokens.toLocaleString()} tokens`,
        valueLabel: formatCurrency(estValue),
        detailDescription: desc,
        txCount: t.count,
        tokensCount: totalTokens,
        color: COLORS.p2pIn,
        href: `/wallet/${t.address}`,
        weight: Math.max(t.totalShares * 0.5, 500),
      });
    });
    if (depositsTotal > 0) {
      nodes.push({
        key: "deposit",
        label: "On-chain Deposit",
        sublabel: "Bridge / CEX direct",
        amountLabel: formatCurrency(depositsTotal),
        detailDescription: `Cumulative on-chain deposits into this wallet totaling ${formatCurrency(depositsTotal)}.`,
        color: COLORS.deposit,
        href: null,
        weight: depositsTotal,
      });
    }
    return nodes;
  }, [funding, groupedInflowsUSD, groupedIncomingP2P, depositsTotal]);

  const outNodes = useMemo<FlowNode[]>(() => {
    const nodes: FlowNode[] = [];
    groupedOutflowsUSD.forEach((f) => {
      nodes.push({
        key: `usd-out-${f.address}`,
        label: f.username || formatAddress(f.address),
        sublabel: `${f.count} transfer${f.count > 1 ? "s" : ""}`,
        amountLabel: `−${formatCurrency(f.totalUsd)}`,
        detailDescription: `Transferred ${formatCurrency(f.totalUsd)} cash out to ${f.username || formatAddress(f.address)} across ${f.count} transaction${f.count > 1 ? "s" : ""}.`,
        color: COLORS.usdOut,
        href: `/wallet/${f.address}`,
        weight: f.totalUsd,
      });
    });
    groupedOutgoingP2P.forEach((t) => {
      const outcomeTag = t.outcomes.length > 0 ? ` (${t.outcomes.join("/")})` : "";
      const totalTokens = Math.round(t.totalShares);
      const estValue = totalTokens * 1.0;
      const desc = `Sent a total of ${totalTokens.toLocaleString()} Polymarket outcome shares (contracts) to ${t.username || formatAddress(t.address)} across ${t.count} separate transaction${t.count > 1 ? "s" : ""}.`;

      nodes.push({
        key: `p2p-out-${t.address}`,
        label: t.username || formatAddress(t.address),
        sublabel: t.markets[0] ? `${t.count}x · ${t.markets[0]}${outcomeTag}` : `${t.count} position transfer${t.count > 1 ? "s" : ""}`,
        amountLabel: `${totalTokens.toLocaleString()} tokens`,
        valueLabel: formatCurrency(estValue),
        detailDescription: desc,
        txCount: t.count,
        tokensCount: totalTokens,
        color: COLORS.p2pOut,
        href: `/wallet/${t.address}`,
        weight: Math.max(t.totalShares * 0.5, 500),
      });
    });
    return nodes;
  }, [groupedOutflowsUSD, groupedOutgoingP2P]);

  const clusterAddresses = useMemo(() => {
    const set = new Set<string>();
    if (funding?.funded_by) set.add(funding.funded_by.toLowerCase());
    groupedIncomingP2P.forEach((n) => set.add(n.address.toLowerCase()));
    groupedOutgoingP2P.forEach((n) => set.add(n.address.toLowerCase()));
    groupedInflowsUSD.forEach((n) => set.add(n.address.toLowerCase()));
    groupedOutflowsUSD.forEach((n) => set.add(n.address.toLowerCase()));
    return set.size;
  }, [funding, groupedIncomingP2P, groupedOutgoingP2P, groupedInflowsUSD, groupedOutflowsUSD]);

  const totalP2PTransfers = (positionTransfers?.total_incoming_count || 0) + (positionTransfers?.total_outgoing_count || 0);
  const totalUsdTransfers = (funding?.total_inflows_count || 0) + (funding?.total_outflows_count || 0);
  const hasLineageData = totalP2PTransfers > 0 || totalUsdTransfers > 0 || !!funding?.funded_by || depositsTotal > 0;

  /* Edge thickness ∝ weight, clamped 1.5–10px (thin marks spec) */
  const edgeWidth = (weight: number): number => {
    const maxWeight = Math.max(...inNodes.map((n) => n.weight), ...outNodes.map((n) => n.weight), 1);
    return Math.max(1.5, Math.min(10, (weight / maxWeight) * 10));
  };

  const handleRowEnter = (node: FlowNode) => {
    setHoveredNode(node.key);
  };

  const handleRowLeave = () => {
    setHoveredNode(null);
  };

  /* Compact one-line flow row — identity via colored mark beside text tokens */
  const FlowRow = ({ node, side }: { node: FlowNode; side: "in" | "out" }) => {
    return (
      <Link
        href={node.href || "#"}
        onClick={(e) => !node.href && e.preventDefault()}
        className="group flex items-center gap-2 w-full px-2.5 py-2 rounded-lg transition-colors hover:bg-surface-2/70"
      >
        <span
          className="w-2 h-2 rounded-full flex-shrink-0 ring-2 ring-surface"
          style={{ backgroundColor: node.color }}
        />
        <span className="min-w-0 flex-1">
          <span className="block text-xs font-semibold text-foreground truncate leading-tight group-hover:underline">
            {node.label}
          </span>
          <span className="block text-[10px] text-muted-fg truncate leading-tight">
            {node.txCount != null && node.sublabel?.includes(" · ") ? (
              <>
                <b className="font-bold text-foreground font-mono">{node.txCount}x</b>
                <span> · {node.sublabel.split(" · ").slice(1).join(" · ")}</span>
              </>
            ) : (
              node.sublabel
            )}
          </span>
        </span>
        <div className="flex-shrink-0 text-right">
          <span className="block font-mono text-[11px] font-bold text-foreground tabular-nums leading-tight">
            {node.amountLabel}
          </span>
          {node.valueLabel && (
            <span className="block font-mono text-[9px] text-muted-fg tabular-nums leading-tight">
              ~{node.valueLabel}
            </span>
          )}
        </div>
        {/* Edge stub — connects row to the SVG layer visually */}
        <svg width="14" height="4" className="flex-shrink-0 -mr-1 opacity-60 group-hover:opacity-100 transition-opacity">
          <rect x="0" y={Math.max(0, (4 - edgeWidth(node.weight)) / 2)} width="14" height={edgeWidth(node.weight)} rx="2" fill={node.color} />
        </svg>
      </Link>
    );
  };

  return (
    <div className="bg-surface rounded-2xl border border-border p-5 shadow-sm space-y-4">
      {/* ── Header & Mode Switcher ─────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3 pb-3 border-b border-border">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-primary-dim text-primary border border-primary/20">
            <GitFork size={18} />
          </div>
          <div>
            <h3 className="font-bold text-foreground text-sm tracking-tight">Capital Lineage</h3>
            <p className="text-xs text-muted-fg mt-0.5">
              Where this wallet&apos;s money came from and where it went — internal transfers, P2P positions & deposits.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1 p-1 bg-surface-2 rounded-xl border border-border">
          <button
            onClick={() => setViewMode("graph")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
              viewMode === "graph" ? "bg-background text-foreground shadow-sm" : "text-muted-fg hover:text-foreground"
            }`}
          >
            <Network size={13} />
            <span>Flow</span>
          </button>
          <button
            onClick={() => setViewMode("ledger")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
              viewMode === "ledger" ? "bg-background text-foreground shadow-sm" : "text-muted-fg hover:text-foreground"
            }`}
          >
            <ListFilter size={13} />
            <span>Ledger</span>
            {totalP2PTransfers + totalUsdTransfers > 0 && (
              <span className="ml-0.5 text-[10px] px-1.5 py-0.5 rounded-full bg-surface-3 text-foreground font-mono">
                {totalP2PTransfers + totalUsdTransfers}
              </span>
            )}
          </button>
        </div>
      </div>

      {viewMode === "graph" ? (
        hasLineageData ? (
          <div className="relative lineage-canvas">
            {/* Column headers */}
            <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] gap-4 mb-3 px-2.5">
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-fg">
                <ArrowDownLeft size={12} style={{ color: COLORS.usdIn }} />
                <span>Inflows</span>
                <span className="ml-auto font-mono normal-case tracking-normal">{inNodes.length} source{inNodes.length !== 1 ? "s" : ""}</span>
              </div>
              <div className="w-[180px]" /> {/* center spacer */}
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-fg">
                <ArrowUpRight size={12} style={{ color: COLORS.usdOut }} />
                <span>Outflows</span>
                <span className="ml-auto font-mono normal-case tracking-normal">{outNodes.length} target{outNodes.length !== 1 ? "s" : ""}</span>
              </div>
            </div>

            {/* Main 3-column flow layout with SVG edge layer */}
            <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] gap-4 items-stretch relative">
              {/* LEFT: Inflow rows */}
              <div className="space-y-1 flex flex-col justify-center min-h-[200px]">
                {inNodes.map((n) => <FlowRow key={n.key} node={n} side="in" />)}
              </div>

              {/* CENTER: Wallet hub */}
              <div className="flex items-center justify-center px-2 relative z-10 min-h-[200px]">
                {/* SVG bezier edges behind the hub */}
                <svg className="absolute inset-0 w-full h-full pointer-events-none" aria-hidden="true">
                  {inNodes.map((n, i) => {
                    const fromY = ((i + 0.5) / (inNodes.length || 1)) * 100;
                    const d = `M 0 ${fromY}% C 40 ${fromY}%, 55 50%, 100 50%`;
                    return (
                      <path
                        key={n.key}
                        d={d}
                        fill="none"
                        stroke={n.color}
                        strokeWidth={edgeWidth(n.weight)}
                        strokeLinecap="round"
                        strokeOpacity={0.35}
                      />
                    );
                  })}
                  {outNodes.map((n, i) => {
                    const toY = ((i + 0.5) / (outNodes.length || 1)) * 100;
                    const d = `M 0 50% C 45 50%, 60 ${toY}, 100 ${toY}`;
                    return (
                      <path
                        key={n.key}
                        d={d}
                        fill="none"
                        stroke={n.color}
                        strokeWidth={edgeWidth(n.weight)}
                        strokeLinecap="round"
                        strokeOpacity={0.35}
                      />
                    );
                  })}
                </svg>

                {/* Hub card */}
                <div className="relative w-[180px] p-3 rounded-xl bg-surface border border-border shadow-md text-center space-y-2">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-muted-fg">This Wallet</div>
                  <div className="font-semibold text-xs text-foreground truncate px-1" title={username || address}>
                    {username || formatAddress(address)}
                  </div>
                  <div className="pt-2 border-t border-border grid grid-cols-2 gap-x-2 gap-y-1 text-left">
                    <div>
                      <span className="block text-[9px] text-muted-fg uppercase tracking-wide">Balance</span>
                      <span className="font-mono text-[11px] font-bold text-foreground">{formatCurrency(balance)}</span>
                    </div>
                    <div>
                      <span className="block text-[9px] text-muted-fg uppercase tracking-wide">Open Pos</span>
                      <span className="font-mono text-[11px] font-bold text-foreground">{formatCurrency(positionValue)}</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* RIGHT: Outflow rows */}
              <div className="space-y-1 flex flex-col justify-center min-h-[200px]">
                {outNodes.length === 0 ? (
                  <div className="h-full flex items-center">
                    <div className="w-full px-3 py-4 rounded-lg border border-dashed border-border text-center text-muted-fg text-xs">
                      Terminal wallet — no outgoing transfers detected
                    </div>
                  </div>
                ) : (
                  outNodes.map((n) => <FlowRow key={n.key} node={n} side="out" />)
                )}
              </div>
            </div>

            {/* Legend & Guide Footer */}
            <div className="pt-3 mt-1 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-3 text-[11px] text-muted-fg flex-wrap">
              <div className="flex items-center gap-4 flex-wrap">
                {[
                  { c: COLORS.parent, l: "Parent funder" },
                  { c: COLORS.usdIn, l: "USD inflow" },
                  { c: COLORS.p2pIn, l: "P2P positions" },
                  { c: COLORS.deposit, l: "On-chain deposit" },
                ].map(({ c, l }) => (
                  <div key={l} className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full ring-2 ring-surface" style={{ backgroundColor: c }} />
                    <span className="text-[10px] text-muted-fg font-medium">{l}</span>
                  </div>
                ))}
              </div>

              <div className="flex items-center gap-2 font-mono text-[10px] text-muted-fg bg-surface-2/60 px-2.5 py-1 rounded-md border border-border">
                <span><b className="text-foreground font-bold">Nx</b> = Transfer transactions</span>
                <span>·</span>
                <span><b className="text-foreground font-bold">Tokens</b> = Polymarket outcome shares (contracts)</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-14 text-center space-y-3">
            <div className="p-4 rounded-2xl bg-surface-2 text-muted-fg border border-border">
              <Network size={28} />
            </div>
            <h4 className="font-bold text-foreground text-sm">No transfers or funding recorded</h4>
            <p className="text-xs text-muted-fg max-w-md">
              This wallet operates with standard CEX/direct deposits only — no ERC-1155 position transfers or internal USDC flows detected.
            </p>
          </div>
        )
      ) : (
        /* ── Ledger Table ───────────────────────────────────────────── */
        <div className="space-y-3">
          <div className="flex items-center gap-1 p-1 bg-surface-2 rounded-xl border border-border overflow-x-auto">
            {([
              ["usd_in", `Funding Received (${inflowsUSD.length})`],
              ["usd_out", `Funding Sent (${outflowsUSD.length})`],
              ["p2p_in", `P2P In (${incomingP2P.length})`],
              ["p2p_out", `P2P Out (${outgoingP2P.length})`],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setLedgerTab(key)}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer whitespace-nowrap ${
                  ledgerTab === key ? "bg-background text-foreground shadow-sm" : "text-muted-fg hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="overflow-x-auto rounded-xl border border-border bg-surface-2/20">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-border bg-surface-2/60 text-muted-fg text-[11px] uppercase tracking-wider">
                  <th className="py-2.5 px-3 font-semibold">
                    {ledgerTab === "usd_in" ? "Funder" : ledgerTab === "usd_out" ? "Recipient" : ledgerTab === "p2p_in" ? "Sender" : "Recipient"}
                  </th>
                  {(ledgerTab.startsWith("p2p") ? [
                    <th key="mkt" className="py-2.5 px-3 font-semibold">Market</th>,
                    <th key="oc" className="py-2.5 px-3 font-semibold text-center">Outcome</th>,
                    <th key="amt" className="py-2.5 px-3 font-semibold text-right">Tokens / Shares</th>,
                    <th key="val" className="py-2.5 px-3 font-semibold text-right">Est. Settle Value</th>,
                  ] : [
                    <th key="asset" className="py-2.5 px-3 font-semibold">Asset</th>,
                    <th key="amt" className="py-2.5 px-3 font-semibold text-right">Amount</th>,
                  ])}
                  <th className="py-2.5 px-3 font-semibold text-right">Date</th>
                  <th className="py-2.5 px-3 font-semibold text-right">Tx</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {(() => {
                  const isP2P = ledgerTab.startsWith("p2p");
                  const isIn = ledgerTab.endsWith("_in");
                  const rows = isP2P
                    ? (isIn ? incomingP2P : outgoingP2P)
                    : (isIn ? inflowsUSD : outflowsUSD);

                  if (rows.length === 0) {
                    return (
                      <tr>
                        <td colSpan={isP2P ? 7 : 5} className="py-10 text-center text-muted-fg text-xs">
                          No {isIn ? "incoming" : "outgoing"} {isP2P ? "P2P position transfers" : "internal funding transfers"} recorded.
                        </td>
                      </tr>
                    );
                  }

                  return rows.map((r: any, i: number) => {
                    const counterpart = isP2P
                      ? (isIn ? r.from_address : r.to_address)
                      : (isIn ? r.funder_address : r.funded_address);
                    const name = isP2P
                      ? (isIn ? r.from_username : r.to_username)
                      : (isIn ? r.funder_username : r.funded_username);
                    const tsField = isP2P ? r.transferred_at : r.funded_at;
                    const tokensAmt = Number(r.amount || 0);
                    return (
                      <tr key={i} className="hover:bg-surface-2/40 transition-colors">
                        <td className="py-2.5 px-3 font-medium">
                          <Link href={`/wallet/${counterpart}`} className="text-primary hover:underline font-mono text-xs">
                            {name || formatAddress(counterpart)}
                          </Link>
                        </td>
                        {isP2P ? (
                          <>
                            <td className="py-2.5 px-3 text-foreground truncate max-w-[240px]" title={r.market_name}>
                              {r.market_name || "—"}
                            </td>
                            <td className="py-2.5 px-3 text-center">
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                                r.outcome === "YES" ? "bg-green-500/10 text-green-600 border-green-500/20" : "bg-red-500/10 text-red-600 border-red-500/20"
                              }`}>
                                {r.outcome || "YES"}
                              </span>
                            </td>
                            <td className="py-2.5 px-3 text-right font-mono font-bold text-foreground tabular-nums">
                              {tokensAmt.toLocaleString(undefined, { maximumFractionDigits: 2 })} tokens
                            </td>
                            <td className="py-2.5 px-3 text-right font-mono font-bold text-foreground tabular-nums">
                              {formatCurrency(tokensAmt * 1.0)}
                            </td>
                          </>
                        ) : (
                          <>
                            <td className="py-2.5 px-3 font-semibold text-foreground">{r.asset || "USDC"}</td>
                            <td className={`py-2.5 px-3 text-right font-mono font-bold tabular-nums ${isIn ? "text-green-600" : "text-purple-400"}`}>
                              {formatCurrency(r.amount_usd || r.amount || 0)}
                            </td>
                          </>
                        )}
                        <td className="py-2.5 px-3 text-right text-muted-fg text-[11px] whitespace-nowrap">
                          {tsField ? new Date(tsField).toLocaleDateString() : "—"}
                        </td>
                        <td className="py-2.5 px-3 text-right">
                          {r.tx_hash ? (
                            <a href={`https://polygonscan.com/tx/${r.tx_hash}`} target="_blank" rel="noreferrer" className="text-muted-fg hover:text-foreground inline-flex items-center">
                              <ExternalLink size={12} />
                            </a>
                          ) : "—"}
                        </td>
                      </tr>
                    );
                  });
                })()}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-[11px] text-muted-fg pt-1">
            <span className="inline-flex items-center gap-1.5"><Layers size={12} /> P2P transfers: {totalP2PTransfers}</span>
            <span className="inline-flex items-center gap-1.5"><DollarSign size={12} /> Internal funding: {totalUsdTransfers}</span>
          </div>
        </div>
      )}
    </div>
  );
}
