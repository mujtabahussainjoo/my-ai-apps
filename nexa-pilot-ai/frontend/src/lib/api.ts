import type {
  Account,
  ActiveProvider,
  ActivityEntry,
  AppSettings,
  Approval,
  ChatMessageRecord,
  Conversation,
  ProviderConfig,
  ProviderSpec,
  SecretStatus,
  StreamEvent,
  ToolInfo,
  ToolRunResult,
} from "./types";

const TOKEN_KEY = "nexapilot.apiToken";
const DEFAULT_BACKEND = "http://127.0.0.1:8765";

function runningInTauri(): boolean {
  if (typeof window === "undefined") return false;
  const globals = window as unknown as Record<string, unknown>;
  if ("__TAURI_INTERNALS__" in globals || "__TAURI__" in globals) return true;
  return window.location.protocol === "tauri:" || window.location.hostname === "tauri.localhost";
}

/**
 * In a packaged Tauri window the app is served from `tauri://localhost` (or
 * `http://tauri.localhost` on Windows), so relative `/api` paths would hit the
 * webview's own asset server instead of the Python backend. Point straight at
 * the loopback backend there and keep relative paths in the Vite dev server,
 * which proxies `/api` for us.
 */
const configuredBase = (import.meta.env.VITE_API_BASE as string | undefined)?.trim();

let runtimeBase = (configuredBase || (runningInTauri() ? DEFAULT_BACKEND : "")).replace(
  /\/+$/,
  "",
);

export const API_BASE = runtimeBase;

function apiUrl(path: string): string {
  return `${runtimeBase}${path}`;
}

export function getApiToken(): string {
  try {
    return window.localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setApiToken(token: string): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage can be unavailable in hardened webviews */
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly setupHint: string;

  constructor(
    message: string,
    options: {
      status?: number;
      code?: string;
      details?: Record<string, unknown>;
      setupHint?: string;
    } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status ?? 0;
    this.code = options.code ?? "network_error";
    this.details = options.details ?? {};
    this.setupHint = options.setupHint ?? "";
  }
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getApiToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

function invalidResponseError(url: string, response: Response, text: string): ApiError {
  const contentType = response.headers.get("content-type") ?? "unknown";
  const isHtml = contentType.includes("text/html") || /^\s*<!doctype html/i.test(text);
  return new ApiError(
    isHtml
      ? "The local backend returned HTML instead of JSON. NexaPilot may be talking to its own UI server or another app on 127.0.0.1:8765."
      : "The local backend returned an unexpected response instead of JSON.",
    {
      status: response.status,
      code: "invalid_response",
      setupHint: `Received ${contentType} from ${url}. Close any other app using port 8765, then restart NexaPilot. On Windows run: netstat -ano | findstr :8765`,
      details: { url, contentType, body: text.slice(0, 200) },
    },
  );
}

type Attempt<T> =
  | { ok: true; payload: T }
  | { ok: false; retry: boolean; error: ApiError };

async function attemptRequest<T>(
  base: string,
  path: string,
  init: RequestInit,
): Promise<Attempt<T>> {
  const url = `${base}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: authHeaders({
        "Content-Type": "application/json",
        ...(init.headers as Record<string, string> | undefined),
      }),
    });
  } catch (cause) {
    return {
      ok: false,
      retry: base === "",
      error: new ApiError("Cannot reach the NexaPilot backend.", {
        code: "backend_unreachable",
        setupHint:
          "Start the backend (uv run nexapilot) or check that it is bound to 127.0.0.1:8765.",
        details: { url, cause: String(cause) },
      }),
    };
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      if (response.ok) {
        return {
          ok: false,
          retry: base === "",
          error: invalidResponseError(url, response, text),
        };
      }
      payload = null;
    }
  }
  if (!response.ok) {
    const body = (payload ?? {}) as Record<string, unknown>;
    const detail = body.detail as Record<string, unknown> | string | undefined;
    const normalized =
      detail && typeof detail === "object" ? (detail as Record<string, unknown>) : body;
    const message =
      typeof detail === "string"
        ? detail
        : String(normalized.message ?? body.message ?? `Request failed (${response.status})`);
    return {
      ok: false,
      retry: false,
      error: new ApiError(message, {
        status: response.status,
        code: String(normalized.code ?? "request_failed"),
        details: (normalized.details as Record<string, unknown>) ?? {},
        setupHint: String(normalized.setup_hint ?? ""),
      }),
    };
  }
  return { ok: true, payload: payload as T };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const bases = runtimeBase ? [runtimeBase] : ["", DEFAULT_BACKEND];
  let lastError: ApiError | null = null;
  for (const base of bases) {
    const result = await attemptRequest<T>(base, path, init);
    if (result.ok) {
      if (base && base !== runtimeBase) runtimeBase = base;
      return result.payload;
    }
    lastError = result.error;
    if (!result.retry) throw result.error;
  }
  throw lastError ?? new ApiError("Cannot reach the NexaPilot backend.");
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () =>
    request<{
      status: string;
      version: string;
      active_provider?: string | null;
      active_model?: string | null;
      environment?: string;
    }>("/api/health"),

  settings: () => request<AppSettings>("/api/settings"),
  updateSettings: (patch: Record<string, unknown>) =>
    request<{ settings: AppSettings }>("/api/settings", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  secrets: () => request<SecretStatus[]>("/api/settings/secrets"),
  setSecret: (name: string, value: string) =>
    request<{ status: string }>(`/api/settings/secrets/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
  deleteSecret: (name: string) =>
    request<{ status: string }>(`/api/settings/secrets/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),

  providers: () => request<ProviderSpec[]>("/api/providers"),
  activeProvider: () => request<ActiveProvider>("/api/providers/active"),
  providerConfigs: () => request<ProviderConfig[]>("/api/providers/configs"),
  saveProvider: (body: Record<string, unknown>) =>
    request<ProviderConfig>("/api/providers/configs", json(body)),
  activateProvider: (body: Record<string, unknown>) =>
    request<ProviderConfig>("/api/providers/activate", json(body)),
  activateSavedProvider: (id: string) =>
    request<ProviderConfig>(`/api/providers/configs/${id}/activate`, { method: "POST" }),
  deleteProvider: (id: string) =>
    request<{ status: string }>(`/api/providers/configs/${id}`, { method: "DELETE" }),
  testProvider: (body: Record<string, unknown>) =>
    request<{ ok: boolean; message: string; latency_ms?: number; capabilities?: unknown }>(
      "/api/providers/test",
      json(body),
    ),

  accounts: () => request<Account[]>("/api/accounts"),
  googleStart: () =>
    request<{ authorization_url: string; state: string }>("/api/accounts/oauth/google/start"),
  connectImap: (body: Record<string, unknown>) => request<Account>("/api/accounts/imap", json(body)),
  disconnectAccount: (id: string) =>
    request<{ status: string }>(`/api/accounts/${id}`, { method: "DELETE" }),
  syncAccount: (id: string) =>
    request<Record<string, unknown>>(`/api/accounts/${id}/sync`, { method: "POST" }),

  conversations: () => request<Conversation[]>("/api/conversations"),
  messages: (id: string) =>
    request<ChatMessageRecord[]>(`/api/conversations/${encodeURIComponent(id)}/messages`),
  cancelChat: (body: { task_run_id?: string; conversation_id?: string }) =>
    request<{ status: string }>("/api/chat/cancel", json(body)),

  approvals: (status = "") =>
    request<Approval[]>(`/api/approvals${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  decideApproval: (id: string, approved: boolean, note = "") =>
    request<Approval>(`/api/approvals/${id}/decide`, json({ approved, note })),
  resumeApproval: (id: string) => request<{ status: string }>(`/api/approvals/${id}/resume`, {
    method: "POST",
  }),

  activity: (limit = 50) => request<ActivityEntry[]>(`/api/activity?limit=${limit}`),

  calendarEvents: (start = "", end = "") =>
    request<Array<Record<string, unknown>>>(
      `/api/calendar/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    ),
  calendarSync: (accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/sync${accountId ? `?account_id=${encodeURIComponent(accountId)}` : ""}`,
      { method: "POST" },
    ),
  calendarList: (accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/calendar-list${accountId ? `?account_id=${encodeURIComponent(accountId)}` : ""}`,
    ),
  calendarListEntry: (calendarId: string, accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/calendar-list/${encodeURIComponent(calendarId)}${
        accountId ? `?account_id=${encodeURIComponent(accountId)}` : ""
      }`,
    ),
  calendarDetails: (calendarId: string, accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/calendars/${encodeURIComponent(calendarId)}${
        accountId ? `?account_id=${encodeURIComponent(accountId)}` : ""
      }`,
    ),
  calendarColors: (accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/colors${accountId ? `?account_id=${encodeURIComponent(accountId)}` : ""}`,
    ),
  calendarSettings: (accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/settings${accountId ? `?account_id=${encodeURIComponent(accountId)}` : ""}`,
    ),
  calendarSetting: (setting: string, accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/settings/${encodeURIComponent(setting)}${
        accountId ? `?account_id=${encodeURIComponent(accountId)}` : ""
      }`,
    ),
  calendarAcl: (calendarId = "primary", accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/acl?calendar_id=${encodeURIComponent(calendarId)}${
        accountId ? `&account_id=${encodeURIComponent(accountId)}` : ""
      }`,
    ),
  calendarFreebusy: (body: Record<string, unknown>, accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/freebusy${accountId ? `?account_id=${encodeURIComponent(accountId)}` : ""}`,
      json(body),
    ),
  calendarEvent: (eventId: string, calendarId = "primary", accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/events/${encodeURIComponent(eventId)}?calendar_id=${encodeURIComponent(
        calendarId,
      )}${accountId ? `&account_id=${encodeURIComponent(accountId)}` : ""}`,
    ),
  calendarEventInstances: (eventId: string, calendarId = "primary", accountId = "") =>
    request<Record<string, unknown>>(
      `/api/calendar/events/${encodeURIComponent(eventId)}/instances?calendar_id=${encodeURIComponent(
        calendarId,
      )}${accountId ? `&account_id=${encodeURIComponent(accountId)}` : ""}`,
    ),

  portfolio: (id = "") =>
    request<Record<string, unknown>>(`/api/finance/portfolio?portfolio_id=${encodeURIComponent(id)}`),
  orders: () => request<Array<Record<string, unknown>>>("/api/finance/orders"),
  watchlist: () => request<Array<Record<string, unknown>>>("/api/finance/watchlist"),

  codingFiles: (path = ".") =>
    request<{ root: string; files: Array<Record<string, unknown>> }>(
      `/api/coding/files?path=${encodeURIComponent(path)}`,
    ),

  tools: () => request<ToolInfo[]>("/api/tools"),
  runTool: (name: string, args: Record<string, unknown>, conversationId = "") =>
    request<ToolRunResult>(`/api/tools/${encodeURIComponent(name)}`, json({
      arguments: args,
      conversation_id: conversationId,
    })),
  decideToolApproval: (tool: string, approvalId: string, approved: boolean, note = "") =>
    request<Approval>(
      `/api/tools/${encodeURIComponent(tool)}/approvals/${encodeURIComponent(approvalId)}`,
      json({ approved, note }),
    ),
};

export interface StreamOptions {
  signal?: AbortSignal;
  onEvent: (event: StreamEvent) => void;
}

async function streamRequest(
  path: string,
  body: unknown,
  { signal, onEvent }: StreamOptions,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...json(body),
      signal,
      headers: authHeaders({ "Content-Type": "application/json", Accept: "text/event-stream" }),
    });
  } catch (cause) {
    if ((cause as Error).name === "AbortError") return;
    throw new ApiError("Cannot reach the NexaPilot backend.", {
      code: "backend_unreachable",
      details: { cause: String(cause) },
    });
  }

  if (!response.ok || !response.body) {
    const text = await response.text();
    let payload: Record<string, unknown> = {};
    try {
      payload = JSON.parse(text) as Record<string, unknown>;
    } catch {
      payload = { message: text || `Request failed (${response.status})` };
    }
    const detail = payload.detail as Record<string, unknown> | undefined;
    const normalized = detail ?? payload;
    throw new ApiError(String(normalized.message ?? "The run failed"), {
      status: response.status,
      code: String(normalized.code ?? "chat_failed"),
      details: (normalized.details as Record<string, unknown>) ?? {},
      setupHint: String(normalized.setup_hint ?? ""),
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary).trim();
        buffer = buffer.slice(boundary + 2);
        if (frame.startsWith("data:")) {
          const payload = frame.slice(5).trim();
          if (payload) {
            try {
              onEvent(JSON.parse(payload) as StreamEvent);
            } catch {
              /* ignore malformed frames rather than breaking the stream */
            }
          }
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export function streamChat(
  body: {
    message: string;
    conversation_id?: string;
    workflow?: string;
    timezone?: string;
  },
  options: StreamOptions,
): Promise<void> {
  return streamRequest("/api/chat", body, options);
}

export function streamApprovalResume(approvalId: string, options: StreamOptions): Promise<void> {
  return streamRequest(`/api/approvals/${encodeURIComponent(approvalId)}/resume`, {}, options);
}
