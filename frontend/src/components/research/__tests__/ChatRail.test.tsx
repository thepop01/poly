import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatRail from "@/components/research/ChatRail";
import type { ResearchMessage, ResultSetSummary } from "@/types/research";

const message = (id: number, role: "user" | "assistant", content: string): ResearchMessage => ({
  message_id: id,
  chat_id: "chat-1",
  run_id: null,
  role,
  content,
  metadata: {},
  created_at: "2026-09-02T00:00:00Z",
});

const result = (id: string, label: string): ResultSetSummary => ({
  result_set_id: id,
  chat_id: "chat-1",
  run_id: null,
  kind: "wallet_set",
  label,
  definition: {},
  summary: {},
  row_count: 3,
  snapshot_at: "2026-09-02T00:00:00Z",
  created_at: "2026-09-02T00:00:00Z",
});

function props(overrides = {}) {
  return {
    chatId: "chat-1",
    messages: [message(1, "user", "find wallets"), message(2, "assistant", "three wallets")],
    results: [result("r1", "3 wallets")],
    busy: false,
    status: null as string | null,
    error: null as string | null,
    streamingText: "",
    restorePrompt: null as string | null,
    onSend: vi.fn(),
    onStop: vi.fn(),
    onConsumeRestore: vi.fn(),
    ...overrides,
  };
}

describe("ChatRail", () => {
  it("submits on Enter and clears the composer", async () => {
    const user = userEvent.setup();
    const p = props({ messages: [] });
    render(<ChatRail {...p} />);
    const box = screen.getByLabelText("Research prompt");
    await user.type(box, "find wallets{Enter}");
    expect(p.onSend).toHaveBeenCalledWith("find wallets");
    expect(box).toHaveValue("");
  });

  it("adds a newline on Shift+Enter without submitting", async () => {
    const user = userEvent.setup();
    const p = props({ messages: [] });
    render(<ChatRail {...p} />);
    const box = screen.getByLabelText("Research prompt") as HTMLTextAreaElement;
    await user.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    expect(p.onSend).not.toHaveBeenCalled();
    expect(box.value).toContain("\n");
  });

  it("blocks empty prompts and disables submit while a run is active", async () => {
    const user = userEvent.setup();
    const p = props({ busy: true, messages: [] });
    render(<ChatRail {...p} />);
    expect(screen.getByLabelText("Research prompt")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(p.onStop).toHaveBeenCalledTimes(1);
    expect(p.onSend).not.toHaveBeenCalled();
  });

  it("concatenates assistant deltas and shows tool status outside bubbles", () => {
    render(
      <ChatRail
        {...props({ status: "Running open_position_overlap…", streamingText: "Two share it." })}
      />,
    );
    expect(screen.getByTestId("chat-streaming")).toHaveTextContent("Two share it.");
    expect(screen.getByTestId("run-status")).toHaveTextContent("Running open_position_overlap…");
    const bubbles = within(screen.getByTestId("chat-messages")).getAllByTestId("chat-bubble");
    expect(bubbles).toHaveLength(2);
  });

  it("restores the failed prompt into the composer for editing", () => {
    const p = props({ restorePrompt: "show overlap", messages: [] });
    render(<ChatRail {...p} />);
    expect(screen.getByLabelText("Research prompt")).toHaveValue("show overlap");
    expect(p.onConsumeRestore).toHaveBeenCalled();
  });

  it("renders result-set chips with labels and counts", () => {
    render(<ChatRail {...props()} />);
    expect(screen.getByText("3 wallets · 3")).toBeInTheDocument();
  });

  it("shows a thinking indicator while busy without deltas", () => {
    render(<ChatRail {...props({ busy: true, status: "Running find_wallets…", messages: [] })} />);
    expect(screen.getByTestId("chat-thinking")).toHaveTextContent(/thinking/i);
  });

  it("hides the thinking indicator when idle or streaming", () => {
    const { rerender } = render(<ChatRail {...props({ messages: [] })} />);
    expect(screen.queryByTestId("chat-thinking")).toBeNull();
    rerender(
      <ChatRail {...props({ busy: true, streamingText: "Partial answer", messages: [] })} />,
    );
    expect(screen.queryByTestId("chat-thinking")).toBeNull();
    expect(screen.getByTestId("chat-streaming")).toBeInTheDocument();
  });
});
