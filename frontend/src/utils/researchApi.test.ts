import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { listPositions, splitNdjsonBuffer, streamResearchRun } from "@/utils/researchApi";

function streamResponse(chunks: (string | Uint8Array)[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(
          typeof chunk === "string" ? encoder.encode(chunk) : chunk,
        );
      }
      controller.close();
    },
  });
  return new Response(body, {
    status,
    headers: { "Content-Type": "application/x-ndjson" },
  });
}

describe("splitNdjsonBuffer", () => {
  it("holds a partial line until the chunk completes", () => {
    const first = splitNdjsonBuffer('{"type":"run.started","run_id":"1');
    expect(first.events).toEqual([]);
    const second = splitNdjsonBuffer(`${first.rest}"}\n{"type":"run.completed","run_id":"1"}\n`);
    expect(second.events).toHaveLength(2);
    expect(second.rest).toBe("");
  });

  it("parses multiple events arriving in one chunk", () => {
    const { events, rest } = splitNdjsonBuffer(
      '{"type":"a","run_id":"1"}\n{"type":"b","run_id":"1"}\n',
    );
    expect(events.map((e) => e.type)).toEqual(["a", "b"]);
    expect(rest).toBe("");
  });

  it("rejects malformed JSON lines", () => {
    expect(() => splitNdjsonBuffer("{oops}\n")).toThrow(/malformed JSON/);
  });
});

describe("streamResearchRun", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("delivers events split across byte chunks plus a final line without newline", async () => {
    const seen: unknown[] = [];
    vi.mocked(fetch).mockResolvedValue(
      streamResponse([
        '{"type":"run.started","run_id":"r1","data":{',
        '}}\n{"type":"run.completed","run_id":"r1","data":{}}',
      ]),
    );
    await streamResearchRun("chat-1", "hi", (e) => seen.push(e), new AbortController().signal);
    expect(seen).toHaveLength(2);
    expect((seen[1] as { type: string }).type).toBe("run.completed");
    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect((init?.body as string)).toBe(JSON.stringify({ prompt: "hi" }));
  });

  it("throws on HTTP errors without retrying", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("unauthorized", { status: 401 }));
    await expect(
      streamResearchRun("chat-1", "hi", () => {}, new AbortController().signal),
    ).rejects.toThrow("Research run failed: 401");
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });

  it("surfaces abort as a cancellation error", async () => {
    const controller = new AbortController();
    controller.abort();
    vi.mocked(fetch).mockRejectedValue(new DOMException("aborted", "AbortError"));
    await expect(
      streamResearchRun("chat-1", "hi", () => {}, controller.signal),
    ).rejects.toThrow();
  });
});

describe("listPositions", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests chat positions with offset and limit and parses response", async () => {
    const mockPage = {
      positions: [
        {
          address: "0x123",
          condition_id: "0xabc",
          market_title: "Market 1",
          outcome: "YES",
          size: 10,
          avg_price: 0.5,
          current_value: 5,
          unrealized_pnl: 1,
          entry_at: null,
          computed_at: null,
        },
      ],
      offset: 10,
      limit: 50,
    };
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(mockPage), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const result = await listPositions("chat-1", 10, 50);
    expect(result).toEqual(mockPage);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/api/v2/research/chats/chat-1/positions?offset=10&limit=50");
    expect(init?.headers).toBeDefined();
  });

  it("throws on HTTP error", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("Not Found", { status: 404 }));
    await expect(listPositions("chat-1")).rejects.toThrow("Research request failed: 404");
  });
});

