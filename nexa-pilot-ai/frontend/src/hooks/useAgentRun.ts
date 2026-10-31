import { useCallback, useRef, useState } from "react";

import { api, streamApprovalResume, streamChat } from "../lib/api";
import type { Approval, Citation, StreamEvent } from "../lib/types";
import { describeError, useApp } from "../state/store";

export interface ToolActivity {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  status: "running" | "ok" | "error";
  message?: string;
}

export interface RunState {
  running: boolean;
  text: string;
  status: string;
  tools: ToolActivity[];
  approvals: Approval[];
  citations: Citation[];
  conversationId: string;
  taskRunId: string;
  lastAnswer: string;
  error: string | null;
}

const INITIAL: RunState = {
  running: false,
  text: "",
  status: "",
  tools: [],
  approvals: [],
  citations: [],
  conversationId: "",
  taskRunId: "",
  lastAnswer: "",
  error: null,
};

export function useAgentRun() {
  const { notify, refresh } = useApp();
  const [state, setState] = useState<RunState>(INITIAL);
  const controller = useRef<AbortController | null>(null);

  const handle = useCallback(
    (event: StreamEvent) => {
      setState((current) => {
        switch (event.type) {
          case "token":
            return { ...current, text: current.text + (event.text ?? "") };
          case "routing":
            return {
              ...current,
              status: event.workflow ? `Routed to ${event.workflow}` : "Routing",
            };
          case "agent_start":
            return { ...current, status: `${event.workflow ?? "Agent"} working` };
          case "tool_start":
            return {
              ...current,
              status: `Running ${event.tool ?? "tool"}`,
              tools: [
                ...current.tools,
                {
                  id: `${event.tool}-${current.tools.length}`,
                  tool: event.tool ?? "tool",
                  arguments: event.arguments ?? {},
                  status: "running",
                },
              ],
            };
          case "tool_end":
            return {
              ...current,
              status: event.tool ? `${event.tool} finished` : current.status,
              tools: current.tools.map((item, index) =>
                index === current.tools.length - 1 ? { ...item, status: "ok" } : item,
              ),
            };
          case "tool_error":
            return {
              ...current,
              status: `${event.tool ?? "tool"} failed`,
              tools: current.tools.map((item, index) =>
                index === current.tools.length - 1
                  ? { ...item, status: "error", message: event.message }
                  : item,
              ),
            };
          case "approval_required":
            return {
              ...current,
              status: "Waiting for your approval",
              approvals: event.approval
                ? [...current.approvals.filter((a) => a.id !== event.approval?.id), event.approval]
                : current.approvals,
            };
          case "error":
            return { ...current, error: event.message ?? "The run failed.", status: "" };
          case "done":
            return {
              ...current,
              lastAnswer: event.answer ?? current.text,
              citations: event.citations ?? current.citations,
              conversationId: event.conversation_id ?? current.conversationId,
              taskRunId: event.task_run_id ?? current.taskRunId,
              status: "",
            };
          case "cancelled":
            return { ...current, status: "Cancelled" };
          default:
            return current;
        }
      });
    },
    [],
  );

  const start = useCallback(
    async (body: {
      message: string;
      conversation_id?: string;
      workflow?: string;
      timezone?: string;
    }) => {
      controller.current?.abort();
      const local = new AbortController();
      controller.current = local;
      setState({ ...INITIAL, running: true, conversationId: body.conversation_id ?? "" });
      try {
        await streamChat(body, { signal: local.signal, onEvent: handle });
      } catch (error) {
        const info = describeError(error);
        setState((current) => ({ ...current, error: info.message }));
        notify("error", info.message, info.hint);
      } finally {
        setState((current) => ({ ...current, running: false }));
        void refresh();
      }
    },
    [handle, notify, refresh],
  );

  const cancel = useCallback(async () => {
    controller.current?.abort();
    setState((current) => ({ ...current, running: false, status: "Cancelled" }));
    try {
      await api.cancelChat({ conversation_id: state.conversationId });
    } catch {
      /* the local abort already stopped the UI */
    }
  }, [state.conversationId]);

  const decide = useCallback(
    async (approvalId: string, approved: boolean) => {
      const local = new AbortController();
      controller.current = local;
      try {
        await api.decideApproval(approvalId, approved);
        setState((current) => ({
          ...current,
          approvals: current.approvals.filter((item) => item.id !== approvalId),
        }));
        if (!approved) {
          notify("info", "Action rejected. Nothing was executed.");
          return;
        }
        setState((current) => ({ ...current, running: true, status: "Running approved action" }));
        await streamApprovalResume(approvalId, { signal: local.signal, onEvent: handle });
      } catch (error) {
        const info = describeError(error);
        notify("error", info.message, info.hint);
      } finally {
        setState((current) => ({ ...current, running: false }));
        void refresh();
      }
    },
    [handle, notify, refresh],
  );

  const reset = useCallback(() => {
    controller.current?.abort();
    setState(INITIAL);
  }, []);

  return { state, start, cancel, decide, reset };
}
