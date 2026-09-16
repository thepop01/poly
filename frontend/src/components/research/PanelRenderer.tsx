"use client";

import type { ResearchPanel } from "@/types/research";
import ConsensusPanel from "./panels/ConsensusPanel";
import MarketTablePanel from "./panels/MarketTablePanel";
import OverlapPanel from "./panels/OverlapPanel";
import WalletTablePanel from "./panels/WalletTablePanel";

export function PanelRenderer({ panel }: { panel: ResearchPanel }) {
  // Key by result set so paging state resets when a panel is re-run.
  const key = panel.result_set_id ?? panel.panel_id;
  switch (panel.panel_type) {
    case "wallet_table":
      return <WalletTablePanel key={key} panel={panel} />;
    case "market_table":
      return <MarketTablePanel key={key} panel={panel} />;
    case "overlap_table":
      return <OverlapPanel key={key} panel={panel} />;
    case "consensus":
      return <ConsensusPanel key={key} panel={panel} />;
    default: {
      const _exhaustive: never = panel.panel_type;
      return (
        <p className="px-3 py-6 text-center text-sm text-danger">
          Unsupported panel type: {String(_exhaustive)}
        </p>
      );
    }
  }
}
