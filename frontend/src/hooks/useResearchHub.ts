"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  PanelMutation,
  ResearchChat,
  ResearchMessage,
  ResearchPanel,
  ResearchPosition,
  ResearchWorkspace,
  ResearchWorkspaceTab,
  ResultSetSummary,
  StreamEvent,
} from "@/types/research";
import {
  createChat,
  createWorkspace,
  deleteChat,
  getResultPage,
  listChats,
  listMessages,
  listPositions,
  listResults,
  listWorkspacePanels,
  listWorkspaceTabs,
  listWorkspaces,
  patchChat,
  patchPanel,
  streamResearchRun,
} from "@/utils/researchApi";

export interface ChatState {
  chats: ResearchChat[];
  archivedChats: ResearchChat[];
  activeChatId: string | null;
  loading: boolean;
  messagesByChat: Record<string, ResearchMessage[]>;
  resultsByChat: Record<string, ResultSetSummary[]>;
  positionsByChat: Record<string, ResearchPosition[]>;
  busyByChat: Record<string, boolean>;
  statusByChat: Record<string, string | null>;
  errorByChat: Record<string, string | null>;
  streamingTextByChat: Record<string, string>;
  restorePromptByChat: Record<string, string | null>;
}

const EMPTY_RESULTS: ResultSetSummary[] = [];
const EMPTY_POSITIONS: ResearchPosition[] = [];

export function useResearchHub() {
  const [chats, setChats] = useState<ResearchChat[]>([]);
  const [workspaces, setWorkspaces] = useState<ResearchWorkspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);
  const [tabsByWorkspace, setTabsByWorkspace] = useState<Record<string, ResearchWorkspaceTab[]>>({});
  const [panelsByWorkspace, setPanelsByWorkspace] = useState<Record<string, ResearchPanel[]>>({});
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messagesByChat, setMessagesByChat] = useState<Record<string, ResearchMessage[]>>({});
  const [resultsByChat, setResultsByChat] = useState<Record<string, ResultSetSummary[]>>({});
  const [positionsByChat, setPositionsByChat] = useState<Record<string, ResearchPosition[]>>({});
  const [busyByChat, setBusyByChat] = useState<Record<string, boolean>>({});
  const [statusByChat, setStatusByChat] = useState<Record<string, string | null>>({});
  const [errorByChat, setErrorByChat] = useState<Record<string, string | null>>({});
  const [streamingTextByChat, setStreamingTextByChat] = useState<Record<string, string>>({});
  const [restorePromptByChat, setRestorePromptByChat] = useState<Record<string, string | null>>({});
  const [loading, setLoading] = useState(true);
  const abortByChat = useRef<Record<string, AbortController>>({});
  const activeIdRef = useRef<string | null>(null);
  const activeWorkspaceRef = useRef<string | null>(null);
  const chatsRef = useRef<ResearchChat[]>([]);
  const workspaceByChatRef = useRef<Record<string, string>>({});
  const panelsRef = useRef<Record<string, ResearchPanel[]>>({});
  const workspaceSelectionVersion = useRef(0);
  const panelMutationQueues = useRef<Record<string, Promise<void>>>({});

  const openChats = chats.filter((c) => !c.is_archived);
  const archivedChats = chats.filter((c) => {
    if (!c.is_archived) return false;
    const msgs = messagesByChat[c.chat_id];
    return msgs === undefined || msgs.length > 0;
  });

  const refreshWorkspaceData = useCallback(async (workspaceId: string) => {
    const [tabs, panels] = await Promise.all([listWorkspaceTabs(workspaceId), listWorkspacePanels(workspaceId)]);
    setTabsByWorkspace((prev) => ({ ...prev, [workspaceId]: tabs.tabs }));
    panelsRef.current[workspaceId] = panels.panels;
    setPanelsByWorkspace((prev) => ({ ...prev, [workspaceId]: panels.panels }));
  }, []);

  const refreshChatData = useCallback(async (chatId: string) => {
    const [messages, results, positions] = await Promise.all([
      listMessages(chatId, 0, 200),
      listResults(chatId).catch(() => ({ results: [] as ResultSetSummary[] })),
      listPositions(chatId, 0, 100).catch(() => null),
    ]);
    setMessagesByChat((prev) => ({ ...prev, [chatId]: messages.messages }));
    setResultsByChat((prev) => ({ ...prev, [chatId]: results.results.slice(0, 20) }));
    if (positions !== null) setPositionsByChat((prev) => ({ ...prev, [chatId]: positions.positions }));
  }, []);

  const activate = useCallback((chatId: string | null) => {
    activeIdRef.current = chatId;
    setActiveChatId(chatId);
    if (chatId) refreshChatData(chatId).catch(() => {});
  }, [refreshChatData]);

  const reloadChats = useCallback(async (selectId?: string | null) => {
    let ws = (await listWorkspaces()).workspaces;
    if (ws.length === 0) ws = [await createWorkspace("Research")];
    setWorkspaces(ws);
    const { chats: all } = await listChats(true);
    chatsRef.current = all;
    workspaceByChatRef.current = Object.fromEntries(all.map((c) => [c.chat_id, c.workspace_id]));
    setChats(all);
    const open = all.filter((c) => !c.is_archived);
    const current = selectId !== undefined ? selectId : activeIdRef.current;
    const next = current && open.some((c) => c.chat_id === current) ? current : open[0]?.chat_id ?? null;
    const workspaceId = next ? all.find((c) => c.chat_id === next)?.workspace_id : ws[0]?.workspace_id ?? null;
    activeIdRef.current = next;
    activeWorkspaceRef.current = workspaceId;
    setActiveChatId(next);
    setActiveWorkspaceId(workspaceId);
    if (workspaceId) refreshWorkspaceData(workspaceId).catch(() => {});
    if (next) refreshChatData(next).catch(() => {});
  }, [refreshChatData, refreshWorkspaceData]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try { await reloadChats(); } catch { /* Auth-gated views render sign-in prompt. */ }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [reloadChats]);

  const selectChat = useCallback((chatId: string) => {
    // Chat selection deliberately does not touch the workspace canvas.
    activate(chatId);
  }, [activate]);

  const handleCreateChat = useCallback(async (workspaceId = activeWorkspaceRef.current) => {
    let target = workspaceId;
    if (!target) {
      let ws = workspaces;
      if (ws.length === 0) {
        const created = await createWorkspace("Research");
        ws = [created];
        setWorkspaces(ws);
      }
      target = ws[0].workspace_id;
      activeWorkspaceRef.current = target;
      setActiveWorkspaceId(target);
      await refreshWorkspaceData(target);
    }
    const chat = await createChat("New research", target);
    workspaceByChatRef.current[chat.chat_id] = chat.workspace_id;
    chatsRef.current = [chat, ...chatsRef.current];
    setChats((prev) => [chat, ...prev]);
    activate(chat.chat_id);
    return chat;
  }, [activate, refreshWorkspaceData, workspaces]);

  const handleRenameChat = useCallback(async (chatId: string, title: string) => {
    const chat = await patchChat(chatId, { title });
    chatsRef.current = chatsRef.current.map((c) => c.chat_id === chatId ? chat : c);
    setChats((prev) => prev.map((c) => c.chat_id === chatId ? chat : c));
  }, []);

  const openRemaining = useCallback((excludeId: string) => {
    const remaining = chatsRef.current.filter((c) => !c.is_archived && c.chat_id !== excludeId);
    return remaining.length ? remaining[0].chat_id : null;
  }, []);

  const handleCloseChat = useCallback(async (chatId: string) => {
    const hasConversation = (messagesByChat[chatId] ?? []).length > 0;
    if (!hasConversation) {
      await deleteChat(chatId).catch(() => {});
      chatsRef.current = chatsRef.current.filter((c) => c.chat_id !== chatId);
      setChats((prev) => prev.filter((c) => c.chat_id !== chatId));
    } else {
      const chat = await patchChat(chatId, { is_archived: true });
      chatsRef.current = chatsRef.current.map((c) => c.chat_id === chatId ? chat : c);
      setChats((prev) => prev.map((c) => c.chat_id === chatId ? chat : c));
    }
    if (activeIdRef.current === chatId) activate(openRemaining(chatId));
  }, [activate, messagesByChat, openRemaining]);

  const handleReopenChat = useCallback(async (chatId: string) => {
    const chat = await patchChat(chatId, { is_archived: false });
    chatsRef.current = chatsRef.current.map((c) => c.chat_id === chatId ? chat : c);
    setChats((prev) => prev.map((c) => c.chat_id === chatId ? chat : c));
    activate(chatId);
  }, [activate]);

  const handleDeleteChat = useCallback(async (chatId: string) => {
    await deleteChat(chatId);
    chatsRef.current = chatsRef.current.filter((c) => c.chat_id !== chatId);
    setChats((prev) => prev.filter((c) => c.chat_id !== chatId));
    if (activeIdRef.current === chatId) activate(openRemaining(chatId));
  }, [activate, openRemaining]);

  const applyEvent = useCallback((chatId: string, event: StreamEvent) => {
    switch (event.type) {
      case "run.started": setStatusByChat((p) => ({ ...p, [chatId]: "Running…" })); break;
      case "tool.started": setStatusByChat((p) => ({ ...p, [chatId]: `Running ${String(event.data.tool_name ?? "analysis")}…` })); break;
      case "result.created": {
        const summary = event.data as unknown as ResultSetSummary;
        setResultsByChat((p) => ({ ...p, [chatId]: [summary, ...(p[chatId] ?? [])].slice(0, 20) }));
        setStatusByChat((p) => ({ ...p, [chatId]: "Running…" })); break;
      }
      case "panel.upserted": {
        const panel = (event.data.panel ?? event.data) as unknown as ResearchPanel;
        const workspaceId = panel.workspace_id ?? workspaceByChatRef.current[chatId];
        if (!workspaceId) break;
        setPanelsByWorkspace((p) => {
          const existing = p[workspaceId] ?? panelsRef.current[workspaceId] ?? [];
          const index = existing.findIndex((x) => x.panel_id === panel.panel_id);
          const next = index >= 0 ? existing.map((x, i) => i === index ? panel : x) : [...existing, panel];
          panelsRef.current[workspaceId] = next;
          return { ...p, [workspaceId]: next };
        }); break;
      }
      case "assistant.delta": setStreamingTextByChat((p) => ({ ...p, [chatId]: `${p[chatId] ?? ""}${String(event.data.text ?? "")}` })); break;
      default: break;
    }
  }, []);

  const finishRun = useCallback(async (chatId: string, prompt: string, failed: { message: string } | null, terminal: StreamEvent | null) => {
    if (terminal?.type === "run.failed") {
      const data = terminal.data as { error_message?: string };
      setErrorByChat((p) => ({ ...p, [chatId]: String(data.error_message ?? "Analysis run failed.") }));
      setRestorePromptByChat((p) => ({ ...p, [chatId]: prompt }));
    }
    setBusyByChat((p) => ({ ...p, [chatId]: false }));
    setStatusByChat((p) => ({ ...p, [chatId]: null }));
    setStreamingTextByChat((p) => ({ ...p, [chatId]: "" }));
    delete abortByChat.current[chatId];
    if (!failed) {
      try { await refreshChatData(chatId); } catch { /* Keep streamed state. */ }
    } else if (failed.message !== "stopped") {
      try { const { messages } = await listMessages(chatId, 0, 200); setMessagesByChat((p) => ({ ...p, [chatId]: messages })); } catch { /* Keep streamed state. */ }
    }
  }, [refreshChatData]);

  const sendPrompt = useCallback(async (chatId: string, prompt: string) => {
    const text = prompt.trim();
    if (!text || busyByChat[chatId]) return;
    abortByChat.current[chatId]?.abort();
    const controller = new AbortController();
    abortByChat.current[chatId] = controller;
    const optimistic: ResearchMessage = { message_id: -Date.now(), chat_id: chatId, run_id: null, role: "user", content: text, metadata: {}, created_at: new Date().toISOString() };
    setMessagesByChat((p) => ({ ...p, [chatId]: [...(p[chatId] ?? []), optimistic] }));
    setBusyByChat((p) => ({ ...p, [chatId]: true })); setErrorByChat((p) => ({ ...p, [chatId]: null }));
    setRestorePromptByChat((p) => ({ ...p, [chatId]: null })); setStreamingTextByChat((p) => ({ ...p, [chatId]: "" })); setStatusByChat((p) => ({ ...p, [chatId]: "Starting…" }));
    let terminal: StreamEvent | null = null; let failure: { message: string } | null = null;
    try { await streamResearchRun(chatId, text, (event) => { if (event.type === "run.completed" || event.type === "run.failed") terminal = event; else applyEvent(chatId, event); }, controller.signal); }
    catch (err) { failure = { message: err instanceof DOMException && err.name === "AbortError" ? "stopped" : "error" }; }
    if (!terminal && !failure) { failure = { message: "error" }; setErrorByChat((p) => ({ ...p, [chatId]: "Stream ended unexpectedly." })); setRestorePromptByChat((p) => ({ ...p, [chatId]: text })); }
    if (failure?.message === "stopped") setRestorePromptByChat((p) => ({ ...p, [chatId]: text }));
    await finishRun(chatId, text, failure, terminal);
  }, [applyEvent, busyByChat, finishRun]);

  const stopRun = useCallback((chatId: string) => { abortByChat.current[chatId]?.abort(); }, []);
  const consumeRestorePrompt = useCallback((chatId: string) => setRestorePromptByChat((p) => ({ ...p, [chatId]: null })), []);

  const mutatePanel = useCallback((workspaceId: string, panelId: string, mutation: PanelMutation): Promise<ResearchPanel> => {
    const prior = panelMutationQueues.current[workspaceId] ?? Promise.resolve();
    let resolveResult!: (panel: ResearchPanel) => void;
    let rejectResult!: (error: unknown) => void;
    const result = new Promise<ResearchPanel>((resolve, reject) => { resolveResult = resolve; rejectResult = reject; });
    const operation = prior.catch(() => {}).then(async () => {
      const previous = panelsRef.current[workspaceId] ?? [];
      const optimistic = previous.map((panel) => panel.panel_id !== panelId ? panel : {
        ...panel,
        state: mutation.state ?? panel.state,
        layout: mutation.floating ? { ...panel.layout, floating: mutation.floating } : panel.layout,
      });
      panelsRef.current[workspaceId] = optimistic;
      setPanelsByWorkspace((p) => ({ ...p, [workspaceId]: optimistic }));
      try {
        const updated = await patchPanel(panelId, mutation);
        const current = panelsRef.current[workspaceId] ?? [];
        const next = current.map((panel) => panel.panel_id === panelId ? updated : panel);
        panelsRef.current[workspaceId] = next;
        setPanelsByWorkspace((p) => ({ ...p, [workspaceId]: next }));
        resolveResult(updated);
      } catch (err) {
        // This operation is serialized, so the snapshot contains no later mutation.
        panelsRef.current[workspaceId] = previous;
        setPanelsByWorkspace((p) => ({ ...p, [workspaceId]: previous }));
        rejectResult(err);
      }
    });
    panelMutationQueues.current[workspaceId] = operation.then(() => undefined, () => undefined);
    return result;
  }, []);

  const setPanelState = useCallback(async (workspaceId: string, panelId: string, state: ResearchPanel["state"]) => { await mutatePanel(workspaceId, panelId, { state }); }, [mutatePanel]);

  const selectWorkspace = useCallback(async (workspaceId: string) => {
    const version = ++workspaceSelectionVersion.current;
    await refreshWorkspaceData(workspaceId);
    if (version !== workspaceSelectionVersion.current) return;
    const chat = chatsRef.current.find((c) => !c.is_archived && c.workspace_id === workspaceId);
    activeWorkspaceRef.current = workspaceId;
    setActiveWorkspaceId(workspaceId);
    if (chat) {
      activate(chat.chat_id);
      return;
    }
    const created = await createChat("New research", workspaceId);
    if (version !== workspaceSelectionVersion.current) return;
    workspaceByChatRef.current[created.chat_id] = created.workspace_id;
    chatsRef.current = [created, ...chatsRef.current];
    setChats((prev) => [created, ...prev]);
    activate(created.chat_id);
  }, [activate, refreshWorkspaceData]);

  return {
    chats: openChats, archivedChats, activeChatId, loading, workspaces, activeWorkspaceId, tabsByWorkspace, panelsByWorkspace,
    messagesByChat, resultsByChat, busyByChat, statusByChat, errorByChat, streamingTextByChat, restorePromptByChat,
    resultsForChat: (chatId: string) => resultsByChat[chatId] ?? EMPTY_RESULTS,
    positionsByChat, positionsForChat: (chatId: string | null) => chatId ? positionsByChat[chatId] ?? EMPTY_POSITIONS : EMPTY_POSITIONS,
    selectChat, selectWorkspace, createChat: handleCreateChat, renameChat: handleRenameChat, closeChat: handleCloseChat,
    reopenChat: handleReopenChat, deleteChat: handleDeleteChat, refreshChatData, refreshWorkspaceData, reloadChats, sendPrompt,
    stopRun, consumeRestorePrompt, setPanelState, mutatePanel, getResultPage,
  };
}

export type ResearchHubApi = ReturnType<typeof useResearchHub>;
