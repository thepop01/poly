import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatTabs from "@/components/research/ChatTabs";
import type { ResearchChat } from "@/types/research";

const chat = (id: string, title: string, archived = false): ResearchChat => ({
  chat_id: id,
  title,
  is_archived: archived,
  created_at: "2026-09-02T00:00:00Z",
  updated_at: "2026-09-02T00:00:00Z",
});

function props(overrides = {}) {
  return {
    chats: [chat("a", "Cricket"), chat("b", "T20")],
    archivedChats: [chat("c", "Old thread", true)],
    activeChatId: "a",
    loading: false,
    onSelect: vi.fn(),
    onCreate: vi.fn(),
    onRename: vi.fn(),
    onClose: vi.fn(),
    onReopen: vi.fn(),
    ...overrides,
  };
}

describe("ChatTabs", () => {
  it("shows a loading state while chats load", () => {
    render(<ChatTabs {...props({ loading: true, chats: [] })} />);
    expect(screen.getByText(/loading chats/i)).toBeInTheDocument();
  });

  it("selects a tab on click and marks it selected", async () => {
    const user = userEvent.setup();
    const p = props();
    render(<ChatTabs {...p} />);
    const tablist = screen.getByRole("tablist");
    const tabs = within(tablist).getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    await user.click(tabs[1]);
    expect(p.onSelect).toHaveBeenCalledWith("b");
  });

  it("creates a New research chat from the + button", async () => {
    const user = userEvent.setup();
    const p = props();
    render(<ChatTabs {...p} />);
    await user.click(screen.getByRole("button", { name: /new research chat/i }));
    expect(p.onCreate).toHaveBeenCalledTimes(1);
  });

  it("renames inline with Enter", async () => {
    const user = userEvent.setup();
    const p = props();
    render(<ChatTabs {...p} />);
    await user.click(screen.getByRole("button", { name: "Rename Cricket" }));
    const input = screen.getByLabelText("Chat title");
    await user.clear(input);
    await user.type(input, "World Cup{Enter}");
    expect(p.onRename).toHaveBeenCalledWith("a", "World Cup");
  });

  it("closes a tab without deleting it", async () => {
    const user = userEvent.setup();
    const p = props();
    render(<ChatTabs {...p} />);
    await user.click(screen.getByRole("button", { name: "Close Cricket" }));
    expect(p.onClose).toHaveBeenCalledWith("a");
  });

  it("reopens an archived chat from the overflow menu", async () => {
    const user = userEvent.setup();
    const p = props();
    render(<ChatTabs {...p} />);
    await user.click(screen.getByRole("button", { name: /reopen closed chats/i }));
    await user.click(screen.getByRole("button", { name: "Old thread" }));
    expect(p.onReopen).toHaveBeenCalledWith("c");
  });

  it("scrolls horizontally when many tabs overflow", () => {
    const many = Array.from({ length: 20 }, (_, i) => chat(`id-${i}`, `Chat ${i}`));
    const { container } = render(<ChatTabs {...props({ chats: many })} />);
    const scroller = container.querySelector(".overflow-x-auto");
    expect(scroller).not.toBeNull();
  });
});
