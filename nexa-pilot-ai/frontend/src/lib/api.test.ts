import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, streamChat } from "./api";
import type { StreamEvent } from "./types";

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client", () => {
  it("returns parsed JSON on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse([{ name: "send_email", requires_approval: true }])),
    );
    const tools = await api.tools();
    expect(tools[0]?.name).toBe("send_email");
  });

  it("maps backend errors to ApiError with setup hints", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "not_configured",
            message: "No coding workspace is configured.",
            retryable: false,
            details: {},
            setup_hint: "Set a workspace folder in Settings → Coding.",
          },
          409,
        ),
      ),
    );
    await expect(api.codingFiles()).rejects.toMatchObject({
      code: "not_configured",
      status: 409,
      setupHint: "Set a workspace folder in Settings → Coding.",
    });
  });

  it("reports an unreachable backend instead of hanging", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    await expect(api.health()).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects HTML from the wrong origin instead of returning null data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          new Response("<!doctype html><html><body>app</body></html>", {
            status: 200,
            headers: { "Content-Type": "text/html" },
          }),
        ),
      ),
    );
    await expect(api.settings()).rejects.toMatchObject({ code: "invalid_response" });
  });

  it("parses SSE frames split across chunks", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"routing","workflow":"email"}\n'));
        controller.enqueue(encoder.encode('\ndata: {"type":"token","text":"Hel'));
        controller.enqueue(encoder.encode('lo"}\n\n'));
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(stream, { status: 200 })),
    );

    const events: StreamEvent[] = [];
    await streamChat({ message: "hi" }, { onEvent: (event) => events.push(event) });
    expect(events.map((event) => event.type)).toEqual(["routing", "token"]);
    expect(events[1]?.text).toBe("Hello");
  });

  it("ignores malformed frames but keeps the stream alive", async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("data: not-json\n\ndata: {\"type\":\"done\"}\n\n"));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream, { status: 200 })));
    const events: StreamEvent[] = [];
    await streamChat({ message: "hi" }, { onEvent: (event) => events.push(event) });
    expect(events).toHaveLength(1);
    expect(events[0]?.type).toBe("done");
  });
});
