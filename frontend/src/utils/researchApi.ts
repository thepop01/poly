"use client";

import { getAuthToken } from "@/utils/api";
import type {
  PanelMutation,
  PositionsPage,
  ResearchChat,
  ResearchMessage,
  ResearchWorkspace,
  ResearchWorkspaceTab,
  ResearchPanel,
  ResultMember,
  ResultSetSummary,
  StreamEvent,
} from "@/types/research";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

function authHeaders(extra: Record<string, string> = {}): HeadersInit {
  const token = getAuthToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: authHeaders(init.headers as Record<string, string> | undefined),
  });
  if (!response.ok) {
    throw new Error(`Research request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function listChats(includeArchived = false): Promise<{ chats: ResearchChat[] }> {
  return request(`/api/v2/research/chats?include_archived=${includeArchived}`);
}

export async function listWorkspaces(): Promise<{ workspaces: ResearchWorkspace[] }> {
  return request(`/api/v2/research/workspaces`);
}

export async function createWorkspace(name?: string): Promise<ResearchWorkspace> {
  // The backend requires a non-empty name; keep the optional UI API ergonomic.
  const workspaceName = name?.trim() || "New workspace";
  return request(`/api/v2/research/workspaces`, {
    method: "POST",
    body: JSON.stringify({ name: workspaceName }),
  });
}

export async function patchWorkspace(
  workspaceId: string,
  patch: { name: string },
): Promise<ResearchWorkspace> {
  return request(`/api/v2/research/workspaces/${workspaceId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteWorkspace(workspaceId: string): Promise<{ deleted: string }> {
  return request(`/api/v2/research/workspaces/${workspaceId}`, { method: "DELETE" });
}

export async function listWorkspaceTabs(
  workspaceId: string,
): Promise<{ tabs: ResearchWorkspaceTab[] }> {
  return request(`/api/v2/research/workspaces/${workspaceId}/tabs`);
}

export async function listWorkspacePanels(
  workspaceId: string,
): Promise<{ panels: ResearchPanel[] }> {
  return request(`/api/v2/research/workspaces/${workspaceId}/panels`);
}

export async function createChat(title?: string, workspaceId?: string): Promise<ResearchChat> {
  const body = {
    ...(title === undefined ? {} : { title }),
    ...(workspaceId === undefined ? {} : { workspace_id: workspaceId }),
  };
  return request(`/api/v2/research/chats`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getChat(chatId: string): Promise<ResearchChat> {
  return request(`/api/v2/research/chats/${chatId}`);
}

export async function patchChat(
  chatId: string,
  patch: { title?: string; is_archived?: boolean },
): Promise<ResearchChat> {
  return request(`/api/v2/research/chats/${chatId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteChat(chatId: string): Promise<{ deleted: string }> {
  return request(`/api/v2/research/chats/${chatId}`, { method: "DELETE" });
}

export async function listMessages(
  chatId: string,
  afterId = 0,
  limit = 50,
): Promise<{ messages: ResearchMessage[] }> {
  return request(
    `/api/v2/research/chats/${chatId}/messages?after_id=${afterId}&limit=${limit}`,
  );
}

export async function listPanels(chatId: string): Promise<{ panels: ResearchPanel[] }> {
  return request(`/api/v2/research/chats/${chatId}/panels`);
}

export async function patchPanel(
  panelId: string,
  mutation: PanelMutation,
): Promise<ResearchPanel> {
  return request(`/api/v2/research/panels/${panelId}`, {
    method: "PATCH",
    body: JSON.stringify(mutation),
  });
}

export async function setPanelState(
  panelId: string,
  state: ResearchPanel["state"],
): Promise<ResearchPanel> {
  return patchPanel(panelId, { state });
}

export async function listResults(chatId: string): Promise<{ results: ResultSetSummary[] }> {
  return request(`/api/v2/research/chats/${chatId}/results`);
}

export async function listPositions(
  chatId: string,
  offset = 0,
  limit = 100,
): Promise<PositionsPage> {
  return request(
    `/api/v2/research/chats/${chatId}/positions?offset=${offset}&limit=${limit}`,
  );
}

export async function getResultPage(
  resultSetId: string,
  offset = 0,
  limit = 100,
): Promise<{ summary: ResultSetSummary; members: ResultMember[] }> {
  return request(
    `/api/v2/research/results/${resultSetId}?offset=${offset}&limit=${limit}`,
  );
}

function parseNdjsonLine(line: string): StreamEvent {
  try {
    return JSON.parse(line) as StreamEvent;
  } catch {
    throw new Error("Research stream contained malformed JSON");
  }
}

/** Parse a buffered NDJSON string, emitting complete lines and keeping the tail. */
export function splitNdjsonBuffer(buffer: string): { events: StreamEvent[]; rest: string } {
  const lines = buffer.split("\n");
  const rest = lines.pop() ?? "";
  const events: StreamEvent[] = [];
  for (const line of lines) {
    if (line.trim()) events.push(parseNdjsonLine(line));
  }
  return { events, rest };
}

// Never retry a run POST automatically: a retry can duplicate a user
// message and result snapshot.
export async function streamResearchRun(
  chatId: string,
  prompt: string,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v2/research/chats/${chatId}/runs`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ prompt }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Research run failed: ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const { events, rest } = splitNdjsonBuffer(buffer);
    buffer = rest;
    for (const event of events) onEvent(event);
    if (done) break;
  }
  if (buffer.trim()) onEvent(parseNdjsonLine(buffer));
}
