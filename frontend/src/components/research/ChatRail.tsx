"use client";

import { useEffect, useRef, useState } from "react";
import type { ResearchMessage, ResultSetSummary } from "@/types/research";

interface ChatRailProps {
  chatId: string | null;
  messages: ResearchMessage[];
  results: ResultSetSummary[];
  busy: boolean;
  status: string | null;
  error: string | null;
  streamingText: string;
  restorePrompt: string | null;
  onSend: (prompt: string) => void;
  onStop: () => void;
  onConsumeRestore: () => void;
}

export default function ChatRail({
  chatId,
  messages,
  results,
  busy,
  status,
  error,
  streamingText,
  restorePrompt,
  onSend,
  onStop,
  onConsumeRestore,
}: ChatRailProps) {
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const [seenRestore, setSeenRestore] = useState<string | null>(null);

  // Adopt a restored prompt once per distinct value, during render, so a
  // failed run's prompt is editable again without an effect-driven update.
  if (restorePrompt !== seenRestore) {
    setSeenRestore(restorePrompt);
    if (restorePrompt && !draft) setDraft(restorePrompt);
  }

  useEffect(() => {
    if (seenRestore) onConsumeRestore();
  }, [seenRestore, onConsumeRestore]);

  useEffect(() => {
    const el = listRef.current;
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight });
    }
  }, [messages, streamingText, status]);

  const submit = () => {
    const text = draft.trim();
    if (!text || busy || !chatId) return;
    setDraft("");
    onSend(text);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-shrink-0 items-center justify-between border-b border-border px-3 py-2">
        <span className="text-sm font-semibold text-foreground">Conversation</span>
        {busy && <span className="live-dot text-xs text-success">live</span>}
      </div>

      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-3" data-testid="chat-messages">
        {messages.length === 0 && !streamingText && !busy ? (
          <p className="text-center text-sm text-subtle">
            Ask a question to start this research thread.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {messages.map((message) =>
              message.role === "tool" ? null : (
                <div
                  key={message.message_id}
                  data-testid="chat-bubble"
                  data-role={message.role}
                  className={
                    message.role === "user"
                      ? "self-end rounded-lg bg-primary/10 px-3 py-2 text-sm text-foreground"
                      : "self-start rounded-lg bg-surface-2 px-3 py-2 text-sm text-foreground"
                  }
                >
                  {message.content}
                </div>
              ),
            )}
            {streamingText && (
              <div
                data-testid="chat-streaming"
                className="self-start rounded-lg bg-surface-2 px-3 py-2 text-sm text-foreground"
              >
                {streamingText}
                <span aria-hidden="true" className="ml-1 inline-block animate-pulse">▍</span>
              </div>
            )}
            {busy && !streamingText && (
              <div
                data-testid="chat-thinking"
                aria-hidden="true"
                className="flex items-center gap-2 self-start rounded-lg bg-surface-2 px-3 py-2 text-sm text-subtle"
              >
                <span className="thinking-dots">
                  <span />
                  <span />
                  <span />
                </span>
                Thinking…
              </div>
            )}
          </div>
        )}
        {results.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Result sets">
            {results.map((result) => (
              <span
                key={result.result_set_id}
                title={`${result.kind} · snapshot ${result.snapshot_at}`}
                className="badge badge-muted"
              >
                {result.label} · {result.row_count}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex-shrink-0 border-t border-border px-3 py-2" role="status" aria-live="polite">
        {status && <div data-testid="run-status" className="mb-1 text-xs text-subtle">{status}</div>}
        {error && (
          <div data-testid="run-error" className="mb-1 text-xs text-danger">
            {error}
          </div>
        )}
        <div className="flex items-end gap-2">
          <textarea
            aria-label="Research prompt"
            value={draft}
            disabled={busy || !chatId}
            rows={2}
            placeholder={chatId ? "Ask about wallets, markets, overlap…" : "Select a chat first"}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            className="min-h-10 flex-1 resize-none rounded-lg border border-border bg-surface px-2 py-1.5 text-sm focus:border-primary disabled:opacity-50"
          />
          {busy ? (
            <button
              type="button"
              onClick={onStop}
              className="rounded-lg border border-danger/40 px-3 py-1.5 text-sm font-semibold text-danger hover:bg-danger/10"
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!draft.trim() || !chatId}
              className="rounded-lg bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary/90 disabled:opacity-40"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
