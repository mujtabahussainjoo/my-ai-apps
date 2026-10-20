# Streaming chat API

`POST /api/v1/chat` handles one customer turn (FR-001). It streams a typed event sequence as
server-sent events (SSE) by default; send `stream=false` for a single JSON `ChatResponse`
(FR-003). This document is the schema + example-client reference required by FR-014.

## Request

```json
{
  "message": "Where is my order?",
  "conversation_id": "conv_123",
  "stream": true
}
```

- `message` (required): customer text, 1–`limits.max_message_chars` characters.
- `conversation_id` (optional): omit to start a new conversation. An unknown id yields an
  `error` event (`code = "not_found"`) in streaming mode, or HTTP `404` in JSON mode.
- `stream` (default `true`).

Headers: `X-User-Id` (optional caller identity), `X-Request-ID` (optional correlation id; echoed
on every event as `request_id` — FR-005).

Response media type is `text/event-stream` with `Cache-Control: no-cache` and
`X-Accel-Buffering: no`.

## Event envelope

Every event is one SSE frame — `event: <name>` plus a single-line JSON `data:` payload:

```
event: token
data: {"event":"token","conversation_id":"conv_123","request_id":"req-1","text":"Your "}

```

All payloads include `conversation_id` and `request_id`. Fields that are `null` are omitted.

| `event` | Extra fields | Meaning |
| --- | --- | --- |
| `message_start` | — | The turn began and the conversation id is known (always first). |
| `tool_start` | `tool`, `call_id` | A tool invocation began. Name only; no arguments (FR-011). |
| `tool_result` | `tool`, `call_id`, `status`, `summary` | A tool finished. Safe status/summary only; never raw output (FR-011). |
| `source` | `citations[]` | Retrieved policy evidence grounding the answer (`document_id`, `chunk_id`, `document_title`, `section_title`, `version`, `score`, FR-033). |
| `token` | `text` | A chunk of the customer-visible answer. Whitespace is preserved: concatenating `text` across all `token` events reconstructs the answer exactly. No chain-of-thought (FR-011). |
| `ticket_created` | `ticket_id`, `external_id`, `provider`, `status`, `url` | An escalation ticket was confirmed created/reused (FR-044). |
| `error` | `code`, `message`, `retryable` | A failure after streaming began. Always followed by a terminal `message_end` (FR-012). `code`/`message` are safe to display. |
| `message_end` | `message_id`, `content`, `resolution_state`, `conversation_status` | Terminal event (always last): the persisted assistant message and final conversation status. |

Ordering: `message_start` → (`tool_start`/`tool_result`/`source`)* → (`token`)* →
(`ticket_created`)? → `message_end`. On failure an `error` precedes the final `message_end`.
The assistant message, tool executions, and final status are persisted even when the turn fails
(FR-009).

If the client disconnects mid-stream, the server cancels the turn and best-effort persists the
partial state as `ERROR` before stopping (FR-013).

## Example client

```python
import json
import httpx

answer = ""
with httpx.stream(
    "POST",
    "http://localhost:8000/api/v1/chat",
    json={"message": "Where is my order?", "stream": True},
    headers={"X-User-Id": "u-7"},
) as response:
    response.raise_for_status()
    event = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            event = line[len("event: ") :]
        elif line.startswith("data: "):
            data = json.loads(line[len("data: ") :])
            if event == "token":
                answer += data["text"]
            elif event == "error":
                print("error:", data["code"], data["message"])
            elif event == "message_end":
                print("status:", data["conversation_status"], "message_id:", data["message_id"])
print(answer)
```

JavaScript (browser `EventSource` cannot POST, so use fetch + a stream reader):

```js
const res = await fetch("/api/v1/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "Where is my order?", stream: true }),
});
const reader = res.body.getReader();
const dec = new TextDecoder();
let buf = "";
let answer = "";
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  buf += dec.decode(value, { stream: true });
  const frames = buf.split("\n\n");
  buf = frames.pop();
  for (const frame of frames) {
    const event = /^event: (.+)$/m.exec(frame)?.[1];
    const data = JSON.parse(frame.replace(/^.*data: /ms, ""));
    if (event === "token") answer += data.text;
  }
}
console.log(answer);
```

## JSON mode

`POST /api/v1/chat` with `"stream": false` returns:

```json
{
  "conversation_id": "conv_123",
  "message": {"id": "msg_1", "role": "assistant", "content": "...", "created_at": "..."},
  "resolution_state": null,
  "request_id": "req-1"
}
```

The schemas live in `src/ecommerce_support/schemas/streaming.py`; the route is
`src/ecommerce_support/api/routes/chat.py`; the generator is
`ChatService.stream` in `src/ecommerce_support/services/chat.py`.
