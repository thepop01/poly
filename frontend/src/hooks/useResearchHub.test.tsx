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
const chat = (id: string, archived = false) => ({
  chat_id: id, workspace_id: workspace.workspace_id, title: id, is_archived: archived,
  created_at: "", updated_at: "",
});

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
