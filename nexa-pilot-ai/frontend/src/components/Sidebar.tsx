import { useApp } from "../state/store";
import { ROUTES, type Route } from "../hooks/useRoute";

const LABELS: Record<Route, string> = {
  chat: "Chat",
  research: "Research",
  travel: "Travel",
  email: "Email",
  calendar: "Calendar",
  finance: "Finance",
  coding: "Coding",
  activity: "Activity",
  accounts: "Accounts",
  settings: "Settings",
};

const ICONS: Record<Route, string> = {
  chat: "M4 5h16v11H8l-4 4V5z",
  research: "M11 4a7 7 0 105.2 11.7L21 21l-1.4-1.4-4.6-4.6A7 7 0 0011 4z",
  travel: "M2 16l20-6-3 9-6-2-3 3-1-4-7 0z",
  email: "M3 5h18v14H3V5zm0 1l9 7 9-7",
  calendar: "M4 5h16v16H4V5zm0 5h16M9 3v4m6-4v4",
  finance: "M4 19V5m0 14h16M8 15l3-4 3 2 4-6",
  coding: "M8 6l-5 6 5 6m8-12l5 6-5 6",
  activity: "M3 12h4l3-7 4 14 3-7h4",
  accounts: "M12 12a4 4 0 100-8 4 4 0 000 8zm-8 9a8 8 0 0116 0",
  settings:
    "M12 15a3 3 0 100-6 3 3 0 000 6zm8-3l2-1-2-4-2 .8a8 8 0 00-1.8-1L15 4h-6l-1 2.8a8 8 0 00-1.8 1L4 7l-2 4 2 1a8 8 0 000 2l-2 1 2 4 2-.8a8 8 0 001.8 1L9 22h6l1-2.8a8 8 0 001.8-1l2 .8 2-4-2-1a8 8 0 000-2z",
};

interface Props {
  route: Route;
  onNavigate: (route: Route) => void;
}

export function Sidebar({ route, onNavigate }: Props) {
  const { active, approvals, accounts } = useApp();
  return (
    <nav className="sidebar" aria-label="Main navigation">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          N
        </span>
        <span className="brand-text">
          <strong>NexaPilot</strong>
          <small>AI assistant</small>
        </span>
      </div>

      <ul className="nav-list">
        {ROUTES.map((item) => (
          <li key={item}>
            <button
              type="button"
              className={`nav-item${route === item ? " active" : ""}`}
              onClick={() => onNavigate(item)}
              aria-current={route === item ? "page" : undefined}
            >
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path d={ICONS[item]} fill="none" stroke="currentColor" strokeWidth="1.7" />
              </svg>
              <span>{LABELS[item]}</span>
              {item === "activity" && approvals.length > 0 ? (
                <span className="count">{approvals.length}</span>
              ) : null}
              {item === "accounts" && accounts.length > 0 ? (
                <span className="count subtle">{accounts.length}</span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>

      <div className="sidebar-footer">
        <span className={`dot ${active?.is_configured ? "ok" : "warn"}`} aria-hidden="true" />
        <div>
          <strong>{active?.provider ? active.provider : "No provider"}</strong>
          <small>{active?.model || "Configure in Settings"}</small>
        </div>
      </div>
    </nav>
  );
}
