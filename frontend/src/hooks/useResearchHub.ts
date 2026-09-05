"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ResearchChat,
  ResearchMessage,
  ResearchPanel,
  ResearchPosition,
  ResultSetSummary,
  StreamEvent,
} from "@/types/research";
import {
  createChat,
  deleteChat,
  getResultPage,
  listChats,
  listMessages,
  listPanels,
  listPositions,
  listResults,
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
  panelsByChat: Record<string, ResearchPanel[]>;
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
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messagesByChat, setMessagesByChat] = useState<Record<string, ResearchMessage[]>>({});
  const [panelsByChat, setPanelsByChat] = useState<Record<string, ResearchPanel[]>>({});
  const [resultsByChat, setResultsByChat] = useState<Record<string, ResultSetSummary[]>>({});
  const [positionsByChat, setPositionsByChat] = useState<Record<string, ResearchPosition[]>>({});
  const [busyByChat, setBusyByChat] = useState<Record<string, boolean>>({});
  const [statusByChat, setStatusByChat] = useState<Record<string, string | null>>({});
  const [errorByChat, setErrorByChat] = useState<Record<string, string | null>>({});
  const [streamingTextByChat, setStreamingTextByChat] = useState<Record<string, string>>({});
  const [restorePromptByChat, setRestorePromptByChat] = useState<Record<string, string | null>>({});
  const [loading, setLoading] = useState(true);
  const abortByChat = useRef<Record<string, AbortController>>({});

  const openChats = chats.filter((c) => !c.is_archived);
  const archivedChats = chats.filter((c) => c.is_archived);

  const refreshChatData = useCallback(async (chatId: string) => {
    const [messages, panels, results, positions] = await Promise.all([
      listMessages(chatId, 0, 200),
      listPanels(chatId),
      listResults(chatId).catch(() => ({ results: [] as ResultSetSummary[] })),
      listPositions(chatId, 0, 100).catch(() => null),
    ]);
    setMessagesByChat((prev) => ({ ...prev, [chatId]: messages.messages }));
    setPanelsByChat((prev) => ({ ...prev, [chatId]: panels.panels }));
    setResultsByChat((prev) => ({ ...prev, [chatId]: results.results.slice(0, 20) }));
    if (positions !== null) {
      setPositionsByChat((prev) => ({ ...prev, [chatId]: positions.positions }));
    }
  }, []);

  const activeIdRef = useRef<string | null>(null);

  const activate = useCallback(
    (chatId: string | null) => {
      activeIdRef.current = chatId;
      setActiveChatId(chatId);
      if (chatId) refreshChatData(chatId).catch(() => {});
    },
    [refreshChatData],
  );

  const reloadChats = useCallback(async (selectId?: string | null) => {
    const { chats: all } = await listChats(true);
    setChats(all);
    const open = all.filter((c) => !c.is_archived);
    // Always keep one chat selected while open chats exist.
    const current = selectId !== undefined ? selectId : activeIdRef.current;
    const next =
      current && open.some((c) => c.chat_id === current)
        ? current
        : open.length > 0
          ? open[0].chat_id
          : null;
    activeIdRef.current = next;
    setActiveChatId(next);
    if (next) refreshChatData(next).catch(() => {});
  }, [refreshChatData]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await reloadChats();
      } catch {
        // Auth-gated views render the sign-in prompt instead.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadChats]);

  const selectChat = useCallback(
    (chatId: string) => {
      activate(chatId);
    },
    [activate],
  );

  const handleCreateChat = useCallback(async () => {
    const chat = await createChat("New research");
    setChats((prev) => [chat, ...prev]);
    activate(chat.chat_id);
    return chat;
  }, [activate]);

  const handleRenameChat = useCallback(async (chatId: string, title: string) => {
    const chat = await patchChat(chatId, { title });
    setChats((prev) => prev.map((c) => (c.chat_id === chatId ? chat : c)));
  }, []);

  const openRemaining = useCallback(
    (excludeId: string): string | null => {
      const remaining = openChats.filter((c) => c.chat_id !== excludeId);
      return remaining.length > 0 ? remaining[0].chat_id : null;
    },
    [openChats],
  );

  const handleCloseChat = useCallback(
    async (chatId: string) => {
      const chat = await patchChat(chatId, { is_archived: true });
      setChats((prev) => prev.map((c) => (c.chat_id === chatId ? chat : c)));
      if (activeIdRef.current === chatId) activate(openRemaining(chatId));
    },
    [activate, openRemaining],
  );

  const handleReopenChat = useCallback(
    async (chatId: string) => {
      const chat = await patchChat(chatId, { is_archived: false });
      setChats((prev) => prev.map((c) => (c.chat_id === chatId ? chat : c)));
      activate(chatId);
    },
    [activate],
  );

  const handleDeleteChat = useCallback(
    async (chatId: string) => {
      await deleteChat(chatId);
      setChats((prev) => prev.filter((c) => c.chat_id !== chatId));
      if (activeIdRef.current === chatId) activate(openRemaining(chatId));
    },
    [activate, openRemaining],
  );

  const applyEvent = useCallback((chatId: string, event: StreamEvent) => {
    switch (event.type) {
      case "run.started":
        setStatusByChat((prev) => ({ ...prev, [chatId]: "Running…" }));
        break;
      case "tool.started":
        setStatusByChat((prev) => ({
          ...prev,
          [chatId]: `Running ${String(event.data.tool_name ?? "analysis")}…`,
        }));
        break;
      case "result.created": {
        const summary = event.data as unknown as ResultSetSummary;
        setResultsByChat((prev) => ({
          ...prev,
          [chatId]: [summary, ...(prev[chatId] ?? [])].slice(0, 20),
        }));
        setStatusByChat((prev) => ({ ...prev, [chatId]: "Running…" }));
        break;
      }
      case "panel.upserted": {
        const panel = (event.data.panel ?? event.data) as unknown as ResearchPanel;
        setPanelsByChat((prev) => {
          const existing = prev[chatId] ?? [];
          const index = existing.findIndex((p) => p.panel_id === panel.panel_id);
          const next =
            index >= 0
              ? existing.map((p, i) => (i === index ? panel : p))
              : [...existing, panel];
          return { ...prev, [chatId]: next };
        });
        break;
      }
      case "assistant.delta":
        setStreamingTextByChat((prev) => ({
          ...prev,
          [chatId]: `${prev[chatId] ?? ""}${String(event.data.text ?? "")}`,
        }));
        break;
      case "run.completed":
      case "run.failed":
        break;
      default:
        break;
    }
  }, []);

  const finishRun = useCallback(
    async (chatId: string, prompt: string, failed: { message: string } | null, terminal: StreamEvent | null) => {
      if (terminal?.type === "run.failed") {
        const data = terminal.data as { error_message?: string };
        setErrorByChat((prev) => ({
          ...prev,
          [chatId]: String(data.error_message ?? "Analysis run failed."),
        }));
        setRestorePromptByChat((prev) => ({ ...prev, [chatId]: prompt }));
      }
      setBusyByChat((prev) => ({ ...prev, [chatId]: false }));
      setStatusByChat((prev) => ({ ...prev, [chatId]: null }));
      setStreamingTextByChat((prev) => ({ ...prev, [chatId]: "" }));
      delete abortByChat.current[chatId];
      if (!failed) {
        try {
          await refreshChatData(chatId);
        } catch {
          // Keep streamed state if the refetch fails.
        }
      } else if (failed.message !== "stopped") {
        try {
          const { messages } = await listMessages(chatId, 0, 200);
          setMessagesByChat((prev) => ({ ...prev, [chatId]: messages }));
        } catch {
          // Keep streamed state if the refetch fails.
        }
      }
    },
    [refreshChatData],
  );

  const sendPrompt = useCallback(
    async (chatId: string, prompt: string) => {
      const text = prompt.trim();
      if (!text || busyByChat[chatId]) return;
      abortByChat.current[chatId]?.abort();
      const controller = new AbortController();
      abortByChat.current[chatId] = controller;
      // Optimistic user bubble so the message shows instantly; the server
      // refetch in finishRun replaces it (negative id marks it local-only).
      const optimistic: ResearchMessage = {
        message_id: -Date.now(),
        chat_id: chatId,
        run_id: null,
        role: "user",
        content: text,
        metadata: {},
        created_at: new Date().toISOString(),
      };
      setMessagesByChat((prev) => ({ ...prev, [chatId]: [...(prev[chatId] ?? []), optimistic] }));
      setBusyByChat((prev) => ({ ...prev, [chatId]: true }));
      setErrorByChat((prev) => ({ ...prev, [chatId]: null }));
      setRestorePromptByChat((prev) => ({ ...prev, [chatId]: null }));
      setStreamingTextByChat((prev) => ({ ...prev, [chatId]: "" }));
      setStatusByChat((prev) => ({ ...prev, [chatId]: "Starting…" }));
      let terminal: StreamEvent | null = null;
      let failure: { message: string } | null = null;
      try {
        await streamResearchRun(
          chatId,
          text,
          (event) => {
            if (event.type === "run.completed" || event.type === "run.failed") {
              terminal = event;
            } else {
              applyEvent(chatId, event);
            }
          },
          controller.signal,
        );
      } catch (err) {
        failure = {
          message: err instanceof DOMException && err.name === "AbortError" ? "stopped" : "error",
        };
      }
      if (!terminal && !failure) {
        failure = { message: "error" };
        setErrorByChat((prev) => ({ ...prev, [chatId]: "Stream ended unexpectedly." }));
        setRestorePromptByChat((prev) => ({ ...prev, [chatId]: text }));
      }
      if (failure?.message === "stopped") {
        setRestorePromptByChat((prev) => ({ ...prev, [chatId]: text }));
      }
      await finishRun(chatId, text, failure, terminal);
    },
    [applyEvent, busyByChat, finishRun],
  );

  const stopRun = useCallback((chatId: string) => {
    abortByChat.current[chatId]?.abort();
  }, []);

  const consumeRestorePrompt = useCallback((chatId: string) => {
    setRestorePromptByChat((prev) => ({ ...prev, [chatId]: null }));
  }, []);

  const setPanelState = useCallback(
    async (chatId: string, panelId: string, state: ResearchPanel["state"]) => {
      const previous = panelsByChat[chatId] ?? [];
      setPanelsByChat((prev) => ({
        ...prev,
        [chatId]: (prev[chatId] ?? []).map((p) =>
          p.panel_id === panelId ? { ...p, state } : p,
        ),
      }));
      try {
        const updated = await patchPanel(panelId, state);
        setPanelsByChat((prev) => ({
          ...prev,
          [chatId]: (prev[chatId] ?? []).map((p) =>
            p.panel_id === panelId ? updated : p,
          ),
        }));
      } catch {
        setPanelsByChat((prev) => ({ ...prev, [chatId]: previous }));
      }
    },
    [panelsByChat],
  );

  return {
    chats: openChats,
    archivedChats,
    activeChatId,
    loading,
    messagesByChat,
    panelsByChat,
    resultsByChat,
    busyByChat,
    statusByChat,
    errorByChat,
    streamingTextByChat,
    restorePromptByChat,
    resultsForChat: (chatId: string) => resultsByChat[chatId] ?? EMPTY_RESULTS,
    positionsByChat,
    positionsForChat: (chatId: string | null) => (chatId ? positionsByChat[chatId] ?? EMPTY_POSITIONS : EMPTY_POSITIONS),
    selectChat,
    createChat: handleCreateChat,
    renameChat: handleRenameChat,
    closeChat: handleCloseChat,
    reopenChat: handleReopenChat,
    deleteChat: handleDeleteChat,
    refreshChatData,
    reloadChats,
    sendPrompt,
    stopRun,
    consumeRestorePrompt,
    setPanelState,
    getResultPage,
  };
}

export type ResearchHubApi = ReturnType<typeof useResearchHub>;
