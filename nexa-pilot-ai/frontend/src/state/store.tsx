import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { ApiError, api } from "../lib/api";
import type { Account, ActiveProvider, AppSettings, Approval, ProviderConfig } from "../lib/types";

export interface Notice {
  id: number;
  kind: "error" | "success" | "info";
  message: string;
  hint?: string;
}

interface AppContextValue {
  settings: AppSettings | null;
  active: ActiveProvider | null;
  configs: ProviderConfig[];
  accounts: Account[];
  approvals: Approval[];
  loading: boolean;
  notices: Notice[];
  notify: (kind: Notice["kind"], message: string, hint?: string) => void;
  dismiss: (id: number) => void;
  refresh: () => Promise<boolean>;
  refreshApprovals: () => Promise<void>;
}

const AppContext = createContext<AppContextValue | null>(null);

let noticeId = 0;

export function describeError(error: unknown): { message: string; hint?: string } {
  if (error instanceof ApiError) {
    return { message: error.message, hint: error.setupHint || undefined };
  }
  if (error instanceof Error) return { message: error.message };
  return { message: String(error) };
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [active, setActive] = useState<ActiveProvider | null>(null);
  const [configs, setConfigs] = useState<ProviderConfig[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [notices, setNotices] = useState<Notice[]>([]);

  const notify = useCallback((kind: Notice["kind"], message: string, hint?: string) => {
    const id = ++noticeId;
    setNotices((current) => [...current, { id, kind, message, hint }]);
    window.setTimeout(() => {
      setNotices((current) => current.filter((notice) => notice.id !== id));
    }, kind === "error" ? 9000 : 4500);
  }, []);

  const dismiss = useCallback((id: number) => {
    setNotices((current) => current.filter((notice) => notice.id !== id));
  }, []);

  const refreshApprovals = useCallback(async () => {
    try {
      const pending = await api.approvals("pending");
      setApprovals(Array.isArray(pending) ? pending : []);
    } catch {
      /* surfaced by the caller when it matters */
    }
  }, []);

  const loadData = useCallback(async (): Promise<{ ok: boolean; error?: unknown }> => {
    try {
      const [nextSettings, nextActive, nextConfigs, nextAccounts] = await Promise.all([
        api.settings(),
        api.activeProvider(),
        api.providerConfigs(),
        api.accounts(),
      ]);
      setSettings(nextSettings);
      setActive(nextActive);
      setConfigs(Array.isArray(nextConfigs) ? nextConfigs : []);
      setAccounts(Array.isArray(nextAccounts) ? nextAccounts : []);
      await refreshApprovals();
      return { ok: true };
    } catch (error) {
      return { ok: false, error };
    }
  }, [refreshApprovals]);

  const refresh = useCallback(async (): Promise<boolean> => {
    const result = await loadData();
    if (result.ok) {
      setLoading(false);
      return true;
    }
    const info = describeError(result.error);
    notify("error", info.message, info.hint);
    return false;
  }, [loadData, notify]);

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;
    let timer: number | undefined;
    const maxAttempts = 60;

    const bootstrap = async () => {
      attempts += 1;
      const result = await loadData();
      if (cancelled) return;
      if (result.ok) {
        setLoading(false);
        return;
      }
      if (attempts < maxAttempts) {
        timer = window.setTimeout(() => void bootstrap(), 1000);
        return;
      }
      setLoading(false);
      const info = describeError(result.error);
      notify("error", info.message, info.hint);
    };

    void bootstrap();
    const poll = window.setInterval(() => void refreshApprovals(), 15_000);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
      window.clearInterval(poll);
    };
  }, [loadData, notify, refreshApprovals]);

  const value = useMemo<AppContextValue>(
    () => ({
      settings,
      active,
      configs,
      accounts,
      approvals,
      loading,
      notices,
      notify,
      dismiss,
      refresh,
      refreshApprovals,
    }),
    [
      settings,
      active,
      configs,
      accounts,
      approvals,
      loading,
      notices,
      notify,
      dismiss,
      refresh,
      refreshApprovals,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const context = useContext(AppContext);
  if (!context) throw new Error("useApp must be used inside AppProvider");
  return context;
}
