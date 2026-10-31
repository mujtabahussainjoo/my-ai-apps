import { useCallback, useEffect, useRef, useState } from "react";

import { ApprovalCard } from "../components/ApprovalCard";
import { Markdown } from "../components/Markdown";
import { Callout, EmptyState } from "../components/ui";
import { useAgentRun } from "../hooks/useAgentRun";
import { api } from "../lib/api";
import { relativeTime, shortDate } from "../lib/format";
import type { ChatMessageRecord, Conversation } from "../lib/types";
import { describeError, useApp } from "../state/store";

export function ChatPage() {
  const { active, notify, refresh } = useApp();
  const { state, start, cancel, decide } = useAgentRun();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState("");
  const [history, setHistory] = useState<ChatMessageRecord[]>([]);
  const [input, setInput] = useState("");
  const bottom = useRef<HTMLDivElement | null>(null);

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await api.conversations());
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  }, [notify]);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (!conversationId) {
      setHistory([]);
      return;
    }
    let cancelled = false;
    void api
      .messages(conversationId)
      .then((messages) => {
        if (!cancelled) setHistory(messages);
      })
      .catch((error: unknown) => {
        const info = describeError(error);
        notify("error", info.message, info.hint);
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, notify]);

  useEffect(() => {
    if (state.conversationId && state.conversationId !== conversationId) {
      setConversationId(state.conversationId);
      void loadConversations();
    }
  }, [state.conversationId, conversationId, loadConversations]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [state.text, history.length, state.tools.length]);

  const send = async () => {
    const message = input.trim();
    if (!message || state.running) return;
    setInput("");
    setHistory((current) => [
      ...current,
      { id: `local-${Date.now()}`, role: "user", content: message, created_at: new Date().toISOString() },
    ]);
    await start({ message, conversation_id: conversationId });
    await loadConversations();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
  };

  const newConversation = () => {
    setConversationId("");
    setHistory([]);
    void refresh();
  };

  return (
    <div className="chat-layout">
      <aside className="conversation-rail">
        <button type="button" className="btn primary block" onClick={newConversation}>
          New conversation
        </button>
        <ul className="conversation-list">
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              <button
                type="button"
                className={`conversation-item${conversation.id === conversationId ? " active" : ""}`}
                onClick={() => setConversationId(conversation.id)}
              >
                <strong>{conversation.title || "Untitled"}</strong>
                <small>
                  {conversation.workflow} · {relativeTime(conversation.updated_at)}
                </small>
              </button>
            </li>
          ))}
          {!conversations.length ? <li className="muted small">No conversations yet.</li> : null}
        </ul>
      </aside>

      <section className="chat-panel">
        <header className="chat-header">
          <div>
            <h1>Chat</h1>
            <p className="muted">
              {active?.is_configured
                ? `${active.provider} · ${active.model}`
                : "No provider configured yet"}
            </p>
          </div>
          {state.running ? (
            <button type="button" className="btn ghost" onClick={() => void cancel()}>
              Stop
            </button>
          ) : null}
        </header>

        <div className="messages">
          {!active?.is_configured ? (
            <Callout kind="warn" title="Configure a model first">
              Open Settings and save an active provider. Every workflow uses that single provider;
              nothing is silently substituted.
            </Callout>
          ) : null}

          {history.length === 0 && !state.text && !state.running ? (
            <EmptyState title="Ask anything">
              Research with citations, manage email and calendar, look up travel and markets, or work
              on code in a restricted workspace. Actions that send, book, trade or delete always ask
              for approval first.
            </EmptyState>
          ) : null}

          {history.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <header>
                <span className="message-role">{message.role === "user" ? "You" : "NexaPilot"}</span>
                <span className="muted small">{shortDate(message.created_at)}</span>
              </header>
              {message.role === "assistant" ? (
                <Markdown text={message.content} />
              ) : (
                <p className="prewrap">{message.content}</p>
              )}
            </article>
          ))}

          {state.text || state.running ? (
            <article className="message assistant live">
              <header>
                <span className="message-role">NexaPilot</span>
                {state.running ? <span className="badge badge-info">streaming</span> : null}
              </header>
              {state.status ? <p className="status-line">{state.status}</p> : null}
              <Markdown text={state.text} />
            </article>
          ) : null}

          {state.tools.length ? (
            <div className="tool-trace">
              {state.tools.map((tool) => (
                <details key={tool.id} open={tool.status === "running"}>
                  <summary>
                    <span className={`dot ${tool.status === "error" ? "warn" : "ok"}`} />
                    <strong>{tool.tool}</strong>
                    <span className="muted small">{tool.status}</span>
                  </summary>
                  <pre>{JSON.stringify(tool.arguments, null, 2)}</pre>
                  {tool.message ? <p className="error-text">{tool.message}</p> : null}
                </details>
              ))}
            </div>
          ) : null}

          {state.approvals.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              busy={state.running}
              onDecide={(approved) => void decide(approval.id, approved)}
            />
          ))}

          {state.error ? <Callout kind="error" title="Run failed">{state.error}</Callout> : null}

          {state.citations.length ? (
            <section className="citations">
              <h3>Sources</h3>
              <ol>
                {state.citations.map((citation, index) => (
                  <li key={`${citation.url ?? index}`}>
                    {citation.url ? (
                      <a href={citation.url} target="_blank" rel="noreferrer noopener">
                        {citation.title || citation.url}
                      </a>
                    ) : (
                      <span>{citation.title || citation.source || "Source"}</span>
                    )}
                    {citation.retrieved_at ? (
                      <span className="muted small"> · retrieved {relativeTime(citation.retrieved_at)}</span>
                    ) : null}
                  </li>
                ))}
              </ol>
            </section>
          ) : null}

          <div ref={bottom} />
        </div>

        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={onKeyDown}
            rows={3}
            placeholder="Message NexaPilot… (Enter to send, Shift+Enter for a new line)"
            aria-label="Message"
          />
          <div className="composer-actions">
            <span className="muted small">
              {state.running ? "Working…" : "Approval required for external actions"}
            </span>
            <button type="submit" className="btn primary" disabled={state.running || !input.trim()}>
              Send
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
