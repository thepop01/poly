# API Reference — AI Research Hub (this backend)

*Added 2026-09-04. Moved here from `API_REFERENCE.md` when that file became
the Polymarket official endpoint catalog. All paths are prefixed with `/api`.
Every endpoint requires `Authorization: Bearer <JWT>` (missing credentials
yield the framework's 401 challenge, consistent with all other endpoints).
Cross-owner chat, result-set, run, and panel IDs return `404` to avoid
revealing existence.*

## Chats

- `POST /api/v2/research/chats` — create a chat. Body: `{title?: string(1–120)}`.
  Returns the chat.
- `GET /api/v2/research/chats?include_archived=false&limit=50` — list owned chats,
  newest first. Archived chats are excluded unless `include_archived=true`.
- `GET /api/v2/research/chats/{chat_id}` — fetch one chat or `404`.
- `PATCH /api/v2/research/chats/{chat_id}` — `{title?, is_archived?}`. Closing a
  tab archives it; history, results, and panels are retained.
- `DELETE /api/v2/research/chats/{chat_id}` — hard-delete the chat (confirmed
  destructive action); result sets, members, runs, messages, and panels cascade.

## Messages, panels, results

- `GET /api/v2/research/chats/{chat_id}/messages?after_id=0&limit=50` — `limit`
  capped at 200, ordered by `message_id ASC`.
- `GET /api/v2/research/chats/{chat_id}/panels` — panels ordered by creation.
- `PATCH /api/v2/research/panels/{panel_id}` — `{state: normal|minimized|maximized|closed}`.
- `GET /api/v2/research/results/{result_set_id}?offset=0&limit=100` — `limit`
  1–200. Returns `{summary, members}` with stable `ordinal` ordering.

## Runs (NDJSON stream)

- `POST /api/v2/research/chats/{chat_id}/runs` — body `{prompt: string(1–4000)}`.
  - Rejects a second running/queued run for the chat with `409`.
  - Rate-limited to 10 run starts/minute/user (SlowAPI).
  - Responds `application/x-ndjson` (`Cache-Control: no-store`,
    `X-Accel-Buffering: no`). Never retried client-side: a retry can duplicate
    the user message and result snapshot.

### Stream events

Each line is `{"type", "run_id", "data"}`. Exactly one terminal event ends
every stream:

| Type | Data |
|---|---|
| `run.started` | `chat_id` |
| `tool.started` | `tool_name`, `arguments` |
| `result.created` | `result_set_id`, `kind`, `label`, `row_count`, `snapshot_at`, `summary` |
| `panel.upserted` | `panel` (full panel JSON) |
| `assistant.delta` | `text` (sentence-sized chunks) |
| `run.completed` | `message_id` |
| `run.failed` | `error_code`, `error_message` (client-safe) |

### Stable error codes

`UNKNOWN_TOOL`, `INVALID_TOOL_ARGS`, `RESULT_ACCESS_DENIED`, `TOOL_ERROR`,
`MAX_TOOL_CALLS`, `ROW_LIMIT`, `TIMEOUT`, `CANCELLED`, `RUN_ERROR`,
`PROVIDER_NOT_CONFIGURED`, `PROVIDER_TIMEOUT`, `PROVIDER_BAD_RESPONSE`,
`PROVIDER_ERROR`. Provider exceptions and SQL text are never returned to
clients; details are logged server-side with `run_id`, `chat_id`, hashed
owner ID, tool name, duration, and row count only.

### LLM configuration

Runs need an LLM key on the server. Set `OPENAI_API_KEY` in `.env` (and
restart the API); without one every run ends in `run.failed` with
`PROVIDER_NOT_CONFIGURED`. `OPENAI_BASE_URL` optionally points the bundled
OpenAI-compatible adapter at another gateway; `RESEARCH_MODEL` selects the
model (default `gpt-5-mini`); `RESEARCH_PROVIDER` selects the adapter —
`responses` (default, OpenAI Responses API) or `chat-completions` (use this
for third-party gateways whose `/v1/responses` translation drops
function-call names). IDE subscriptions (e.g. Antigravity) expose no API
endpoint themselves, but a local OpenAI-compatible proxy in front of one
works via `OPENAI_BASE_URL` + `chat-completions`, provided the served model
follows function-call schemas (Claude models do; exact-match scope filters
are case-insensitive, so `Sports` matches stored `SPORTS`).
