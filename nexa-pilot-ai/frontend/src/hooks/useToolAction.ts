import { useCallback, useState } from "react";

import { api } from "../lib/api";
import type { Approval, ToolRunResult } from "../lib/types";
import { describeError, useApp } from "../state/store";

interface PendingApproval {
  tool: string;
  args: Record<string, unknown>;
  approval: Approval;
}

export function useToolAction() {
  const { notify, refresh } = useApp();
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingApproval | null>(null);
  const [result, setResult] = useState<ToolRunResult | null>(null);

  const run = useCallback(
    async (tool: string, args: Record<string, unknown> = {}): Promise<ToolRunResult | null> => {
      setBusy(true);
      try {
        const response = await api.runTool(tool, args);
        if (response.status === "approval_required") {
          setPending({ tool, args, approval: response.approval });
          setResult(null);
          return null;
        }
        setPending(null);
        setResult(response);
        return response;
      } catch (error) {
        const info = describeError(error);
        notify("error", info.message, info.hint);
        return null;
      } finally {
        setBusy(false);
        void refresh();
      }
    },
    [notify, refresh],
  );

  const approve = useCallback(
    async (approved: boolean) => {
      if (!pending) return;
      setBusy(true);
      try {
        await api.decideToolApproval(pending.tool, pending.approval.id, approved);
        if (!approved) {
          notify("info", "Action rejected. Nothing was executed.");
          setPending(null);
          return;
        }
        const response = await api.runTool(pending.tool, pending.args);
        setPending(null);
        if (response.status === "approval_required") {
          setPending({ tool: pending.tool, args: pending.args, approval: response.approval });
        } else {
          setResult(response);
        }
      } catch (error) {
        const info = describeError(error);
        notify("error", info.message, info.hint);
      } finally {
        setBusy(false);
        void refresh();
      }
    },
    [notify, pending, refresh],
  );

  return { busy, pending, result, run, approve, setPending, setResult };
}
