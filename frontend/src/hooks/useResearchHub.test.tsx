import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { useResearchHub } from "./useResearchHub";
import type { ResearchPanel } from "@/types/research";
import * as api from "@/utils/researchApi";

vi.mock("@/utils/researchApi");

const mocked = api as vi.Mocked<typeof api>;
const workspace = { workspace_id: "workspace-1", name: "Research", created_at: "", updated_at: "" };
const panel = (id: string, workspaceId = workspace.workspace_id): ResearchPanel => ({
  panel_id: id, workspace_id: workspaceId, source_chat_id: "chat-a", result_set_id: null,
  panel_type: "wallet_table", panel_key: id, title: id, state: "normal",
  layout: { col_span: 4, min_height: 200, order: 0 }, config: {}, created_at: "", updated_at: "",
});
const chat = (id: string, archived = false, workspaceId = workspace.workspace_id) => ({
  chat_id: id, workspace_id: workspaceId, title: id, is_archived: archived,
  created_at: "", updated_at: "",
});
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listWorkspaces.mockResolvedValue({ workspaces: [workspace] });
  mocked.listChats.mockResolvedValue({ chats: [chat("chat-a"), chat("chat-b")] });
  mocked.listWorkspaceTabs.mockResolvedValue({ tabs: [] });
  mocked.listWorkspacePanels.mockResolvedValue({ panels: [panel("panel-1")] });
  mocked.listMessages.mockImplementation(async (id) => ({ messages: [{ message_id: 1, chat_id: id, run_id: null, role: "user", content: id, metadata: {}, created_at: "" }] }));
  mocked.listResults.mockImplementation(async (chatId) => ({ results: [{ result_set_id: chatId, chat_id: chatId, run_id: null, kind: "x", label: "x", definition: {}, summary: {}, row_count: 0, snapshot_at: "", created_at: "" }] }));
  mocked.listPositions.mockResolvedValue({ positions: [], offset: 0, limit: 100 });
  mocked.patchPanel.mockResolvedValue(panel("panel-1"));
});

test("keeps the workspace canvas when selecting another chat", async () => {
  const { result } = renderHook(() => useResearchHub());
  await waitFor(() => expect(result.current.activeChatId).toBe("chat-a"));
  expect(result.current.panelsByWorkspace["workspace-1"]).toHaveLength(1);
  await act(async () => result.current.selectChat("chat-b"));
  expect(result.current.activeChatId).toBe("chat-b");
  expect(result.current.panelsByWorkspace["workspace-1"]).toHaveLength(1);
  expect(mocked.listWorkspacePanels).toHaveBeenCalledTimes(1);
});

test("stores streamed panel events under panel workspace", async () => {
  const { result } = renderHook(() => useResearchHub());
  await waitFor(() => expect(result.current.activeChatId).toBe("chat-a"));
  mocked.streamResearchRun.mockImplementation(async (_id, _prompt, onEvent) => {
    onEvent({ type: "panel.upserted", run_id: "run", data: { panel: panel("stream-panel") } });
    onEvent({ type: "run.completed", run_id: "run", data: {} });
  });
  await act(async () => result.current.sendPrompt("chat-a", "hello"));
  expect(result.current.panelsByWorkspace["workspace-1"].map((p) => p.panel_id)).toContain("stream-panel");
});

test("ignores stale overlapping workspace selections", async () => {
  const workspace2 = { ...workspace, workspace_id: "workspace-2" };
  mocked.listWorkspaces.mockResolvedValue({ workspaces: [workspace, workspace2] });
  mocked.listChats.mockResolvedValue({ chats: [chat("chat-a"), chat("chat-b", false, workspace2.workspace_id)] });
  const first = deferred<{ tabs: []; panels: ResearchPanel[] }>();
  const second = deferred<{ tabs: []; panels: ResearchPanel[] }>();
  mocked.listWorkspaceTabs.mockImplementation(async (id) => id === "workspace-1" ? first.promise.then((x) => ({ tabs: x.tabs })) : second.promise.then((x) => ({ tabs: x.tabs })));
  mocked.listWorkspacePanels.mockImplementation(async (id) => id === "workspace-1" ? first.promise : second.promise);
  const { result } = renderHook(() => useResearchHub());
  await waitFor(() => expect(result.current.activeChatId).toBe("chat-a"));
  const a = result.current.selectWorkspace("workspace-1");
  const b = result.current.selectWorkspace("workspace-2");
  second.resolve({ tabs: [], panels: [panel("two", "workspace-2")] });
  await act(async () => { await b; });
  first.resolve({ tabs: [], panels: [panel("one")] });
  await act(async () => { await a; });
  expect(result.current.activeWorkspaceId).toBe("workspace-2");
  expect(result.current.activeChatId).toBe("chat-b");
});

test("keeps streamed panels when a later mutation runs", async () => {
  const { result } = renderHook(() => useResearchHub());
  await waitFor(() => expect(result.current.activeChatId).toBe("chat-a"));
  mocked.streamResearchRun.mockImplementationOnce(async (_id, _prompt, onEvent) => {
    onEvent({ type: "panel.upserted", run_id: "run", data: { panel: panel("panel-2") } });
    onEvent({ type: "run.completed", run_id: "run", data: {} });
  });
  await act(async () => { await result.current.sendPrompt("chat-a", "hello"); });
  mocked.patchPanel.mockResolvedValueOnce({ ...panel("panel-1"), state: "minimized" });
  await act(async () => { await result.current.mutatePanel("workspace-1", "panel-1", { state: "minimized" }); });
  expect(result.current.panelsByWorkspace["workspace-1"].map((item) => item.panel_id)).toEqual(["panel-1", "panel-2"]);
});

test("serializes concurrent panel mutations without stale rollback", async () => {
  const first = deferred<ResearchPanel>();
  const second = deferred<ResearchPanel>();
  mocked.patchPanel.mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise);
  const { result } = renderHook(() => useResearchHub());
  await waitFor(() => expect(result.current.activeChatId).toBe("chat-a"));
  const one = result.current.mutatePanel("workspace-1", "panel-1", { state: "minimized" });
  const two = result.current.mutatePanel("workspace-1", "panel-1", { state: "maximized" });
  first.reject(new Error("first failed"));
  await expect(one).rejects.toThrow("first failed");
  first.resolve(panel("panel-1"));
  second.resolve({ ...panel("panel-1"), state: "maximized" });
  await act(async () => { await two; });
  expect(result.current.panelsByWorkspace["workspace-1"][0].state).toBe("maximized");
});

test("rolls back only the mutated workspace", async () => {
  const workspace2 = { ...workspace, workspace_id: "workspace-2" };
  const panel2 = panel("panel-2", workspace2.workspace_id);
  mocked.patchPanel.mockRejectedValueOnce(new Error("nope"));
  const { result } = renderHook(() => useResearchHub());
  await waitFor(() => expect(result.current.activeChatId).toBe("chat-a"));
  await act(async () => {
    // Event reducer is exercised through the public stream path for a second workspace.
    mocked.streamResearchRun.mockImplementationOnce(async (_id, _prompt, onEvent) => {
      onEvent({ type: "panel.upserted", run_id: "run", data: { panel: panel2 } });
      onEvent({ type: "run.completed", run_id: "run", data: {} });
    });
    await result.current.sendPrompt("chat-a", "hello");
  });
  await expect(act(async () => result.current.mutatePanel("workspace-1", "panel-1", { state: "minimized" }))).rejects.toThrow("nope");
  expect(result.current.panelsByWorkspace["workspace-2"]).toEqual([panel2]);
  expect(result.current.panelsByWorkspace["workspace-1"]).toEqual([panel("panel-1")]);
});
