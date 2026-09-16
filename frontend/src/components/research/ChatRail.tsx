"use client";

import { useEffect, useRef, useState } from "react";
import type { ResearchMessage, ResultSetSummary } from "@/types/research";
import { Send, Square, Paperclip, Bot, User, Sparkles, Layers } from "lucide-react";

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

const PROMPT_SUGGESTIONS = [
  "Find top Cricket wallets with >70% win rate",
  "Show open position overlap in election markets",
  "Analyze outcome consensus on high-volume markets",
];

function formatTime(dateStr: string) {
  try {
    return new Date(dateStr).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // A failed/stopped run hands its prompt back once for editing. Adopt it in
  // an effect and consume it so repeats work.
  useEffect(() => {
    if (restorePrompt) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDraft((prev) => prev || restorePrompt);
      onConsumeRestore();
    }
  }, [restorePrompt, onConsumeRestore]);

  useEffect(() => {
    const el = listRef.current;
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [messages, streamingText, status]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, [draft]);

  const submit = () => {
    const text = draft.trim();
    if (!text || busy || !chatId) return;
    setDraft("");
    onSend(text);
  };

  const charCount = draft.length;
  const charLimit = 2000;
  const nearLimit = charCount > charLimit * 0.85;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="chat-rail-header">
        <div className="flex items-center gap-1.5">
          <div className="chat-rail-icon">
            <Bot size={11} />
          </div>
          <div>
            <span className="text-[11px] font-semibold text-foreground leading-none block">Research Terminal</span>
            <span className="text-[9px] text-subtle block font-mono mt-0.5">Antigravity AI · v2</span>
          </div>
        </div>
        {busy ? (
          <span className="chat-status-chip chat-status-live">
            <span className="chat-live-dot" />
            live
          </span>
        ) : (
          <span className="text-[9px] font-mono text-subtle px-1 py-0.5 rounded bg-surface-2 border border-border">
            READY
          </span>
        )}
      </div>

      {/* Status / error banner */}
      {(status || error) && (
        <div className={`chat-status-banner ${error ? "chat-status-error" : "chat-status-thinking"}`} role="status" aria-live="polite">
          {error ? (
            <div data-testid="run-error" className="text-[11px] text-danger">{error}</div>
          ) : (
            <div data-testid="run-status" className="text-[11px] text-subtle">{status}</div>
          )}
        </div>
      )}

      {/* Message list */}
      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-2 py-2" data-testid="chat-messages">
        {messages.length === 0 && !streamingText && !busy ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center py-4 px-2">
            <div className="chat-empty-icon">
              <Bot size={18} className="text-primary" />
            </div>
            <div>
              <h4 className="text-xs font-semibold text-foreground">AI Research Terminal</h4>
              <p className="text-[11px] text-subtle mt-0.5 max-w-[210px] leading-snug">
                Query wallets, compare market positions, discover consensus, and explore historical evidence.
              </p>
            </div>
            <div className="w-full space-y-1 pt-1">
              <p className="text-[9px] font-semibold text-subtle uppercase tracking-wider text-left">
                Suggested Prompts
              </p>
              {PROMPT_SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => {
                    setDraft(suggestion);
                    textareaRef.current?.focus();
                  }}
                  className="chat-suggestion-chip w-full"
                >
                  <Sparkles size={10} className="text-primary flex-shrink-0" />
                  <span className="truncate">{suggestion}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {messages.map((message) =>
              message.role === "tool" ? null : (
                <div
                  key={message.message_id}
                  data-testid="chat-bubble"
                  data-role={message.role}
                  className={message.role === "user" ? "chat-bubble-user" : "chat-bubble-ai"}
                >
                  {/* Role avatar */}
                  <div className={message.role === "user" ? "chat-bubble-avatar chat-bubble-avatar-user" : "chat-bubble-avatar chat-bubble-avatar-ai"}>
                    {message.role === "user" ? <User size={9} /> : <Bot size={9} />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-foreground leading-normal whitespace-pre-wrap">{message.content}</p>
                    {(message as { created_at?: string }).created_at && (
                      <p className="text-[9px] text-subtle mt-0.5">
                        {formatTime((message as { created_at: string }).created_at)}
                      </p>
                    )}
                  </div>
                </div>
              ),
            )}

            {/* Streaming AI response */}
            {streamingText && (
              <div data-testid="chat-streaming" className="chat-bubble-ai">
                <div className="chat-bubble-avatar chat-bubble-avatar-ai">
                  <Bot size={9} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-foreground leading-normal whitespace-pre-wrap">
                    {streamingText}
                    <span aria-hidden="true" className="ml-1 inline-block animate-pulse text-primary">▍</span>
                  </p>
                </div>
              </div>
            )}

            {/* Thinking indicator */}
            {busy && !streamingText && (
              <div data-testid="chat-thinking" aria-hidden="true" className="chat-bubble-ai">
                <div className="chat-bubble-avatar chat-bubble-avatar-ai">
                  <Bot size={9} />
                </div>
                <div className="flex items-center gap-1.5 py-0.5">
                  <span className="thinking-dots">
                    <span />
                    <span />
                    <span />
                  </span>
                  <span className="text-[11px] text-subtle">Thinking…</span>
                </div>
              </div>
            )}

            {/* Result set badges — after last AI message */}
            {results.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-1" aria-label="Result sets">
                {results.map((result) => (
                  <span
                    key={result.result_set_id}
                    title={`${result.kind} · snapshot ${result.snapshot_at}`}
                    className="chat-result-chip"
                  >
                    <Layers size={9} className="text-primary" />
                    <span>{result.label} · {result.row_count}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Chat input area */}
      <div className="chat-input-wrapper" role="region" aria-label="Chat input">
        <div className={`chat-input-box ${busy ? "chat-input-box-busy" : ""} ${draft.length > 0 && !busy ? "chat-input-box-active" : ""}`}>
          {/* Textarea */}
          <textarea
            ref={textareaRef}
            aria-label="Research prompt"
            value={draft}
            disabled={busy || !chatId}
            rows={1}
            placeholder={chatId ? "Ask about wallets, markets, overlap…" : "Select a chat first"}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            className="chat-textarea"
          />

          {/* Input controls row */}
          <div className="chat-input-controls">
            {/* Left: attach + model badge */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={busy || !chatId}
                className="chat-attach-btn"
                title="Attach file (coming soon)"
                aria-label="Attach file"
              >
                <Paperclip size={11} />
              </button>
              <span className="chat-model-chip">Antigravity AI</span>
            </div>

            {/* Right: char count + send/stop */}
            <div className="flex items-center gap-1.5">
              {draft.length > 0 && (
                <span className={`chat-char-count ${nearLimit ? "text-warning" : ""}`}>
                  {charCount}/{charLimit}
                </span>
              )}
              {!draft && !busy && (
                <span className="chat-shortcut-hint">↵ Run</span>
              )}
              {busy ? (
                <button
                  type="button"
                  onClick={onStop}
                  className="chat-stop-btn"
                  aria-label="Stop"
                >
                  <Square size={10} />
                  <span>Stop</span>
                </button>
              ) : (
                <button
                  type="button"
                  onClick={submit}
                  disabled={!draft.trim() || !chatId}
                  className="chat-send-btn"
                  aria-label="Send message"
                >
                  <Send size={11} />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
