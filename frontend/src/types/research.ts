/** Shared Research Hub UI contracts. Mirror the backend JSON shapes. */

export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type PanelState = "normal" | "minimized" | "maximized" | "closed";
export type PanelType = "wallet_table" | "market_table" | "overlap_table" | "consensus";
export type MessageRole = "user" | "assistant" | "tool";

export interface ResearchChat {
  chat_id: string;
  title: string;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface ResearchMessage {
  message_id: number;
  chat_id: string;
  run_id: string | null;
  role: MessageRole;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface PanelLayout {
  col_span: 4 | 6 | 8 | 12;
  min_height: number;
  order: number;
}

export interface ResearchPanel {
  panel_id: string;
  chat_id: string;
  result_set_id: string | null;
  panel_type: PanelType;
  panel_key: string;
  title: string;
  state: PanelState;
  layout: PanelLayout;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ResultSetSummary {
  result_set_id: string;
  chat_id: string;
  run_id: string | null;
  kind: string;
  label: string;
  definition: Record<string, unknown>;
  summary: Record<string, unknown>;
  row_count: number;
  snapshot_at: string;
  created_at: string;
}

export interface ResultMember {
  ordinal: number;
  entity_type: string;
  entity_key: string;
  payload: Record<string, unknown>;
}

export interface ResearchPosition {
  address: string;
  condition_id: string;
  market_title: string | null;
  outcome: string | null;
  size: number | null;
  avg_price: number | null;
  current_value: number | null;
  unrealized_pnl: number | null;
  entry_at: string | null;
  computed_at: string | null;
}

export interface PositionsPage {
  positions: ResearchPosition[];
  offset: number;
  limit: number;
}


export type StreamEventType =
  | "run.started"
  | "tool.started"
  | "result.created"
  | "panel.upserted"
  | "assistant.delta"
  | "run.completed"
  | "run.failed";

export interface StreamEvent {
  type: StreamEventType;
  run_id: string;
  data: Record<string, unknown>;
}

export const TERMINAL_EVENTS: StreamEventType[] = ["run.completed", "run.failed"];

export function isTerminalEvent(type: string): boolean {
  return (TERMINAL_EVENTS as string[]).includes(type);
}
