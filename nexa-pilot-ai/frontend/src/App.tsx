import type { ComponentType } from "react";

import { AccountsPage } from "./pages/AccountsPage";
import { ActivityPage } from "./pages/ActivityPage";
import { CalendarPage } from "./pages/CalendarPage";
import { ChatPage } from "./pages/ChatPage";
import { CodingPage } from "./pages/CodingPage";
import { EmailPage } from "./pages/EmailPage";
import { FinancePage } from "./pages/FinancePage";
import { ResearchPage } from "./pages/ResearchPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TravelPage } from "./pages/TravelPage";
import { Sidebar } from "./components/Sidebar";
import { Callout, Toasts } from "./components/ui";
import { useRoute, type Route } from "./hooks/useRoute";
import { AppProvider, useApp } from "./state/store";

const PAGES: Record<Route, ComponentType> = {
  chat: ChatPage,
  research: ResearchPage,
  travel: TravelPage,
  email: EmailPage,
  calendar: CalendarPage,
  finance: FinancePage,
  coding: CodingPage,
  activity: ActivityPage,
  accounts: AccountsPage,
  settings: SettingsPage,
};

function Shell() {
  const [route, navigate] = useRoute();
  const { settings, loading, refresh } = useApp();
  const Page = PAGES[route];

  return (
    <div className="app">
      <Sidebar route={route} onNavigate={navigate} />
      <main className="main">
        {loading ? (
          <div className="page">
            <p className="muted">Connecting to the local backend…</p>
          </div>
        ) : !settings ? (
          <div className="page">
            <Callout kind="error" title="Backend unavailable">
              <p>
                NexaPilot could not reach its local backend on <code>127.0.0.1:8765</code>.
                The bundled server starts with the app; a first launch can take a few seconds.
              </p>
              <p className="muted">
                If this persists, check <code>%APPDATA%\nexapilot\logs</code> (Windows) or{" "}
                <code>~/.local/share/nexapilot/logs</code> and restart the app.
              </p>
              <button type="button" className="btn primary" onClick={() => void refresh()}>
                Retry connection
              </button>
            </Callout>
          </div>
        ) : (
          <Page />
        )}
      </main>
      <Toasts />
    </div>
  );
}

export function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
