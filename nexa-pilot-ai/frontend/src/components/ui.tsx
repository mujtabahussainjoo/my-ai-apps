import type { ReactNode } from "react";

import { useApp } from "../state/store";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p className="muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="row">{actions}</div> : null}
    </header>
  );
}

export function Card({
  title,
  actions,
  children,
  className = "",
}: {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`.trim()}>
      {(title || actions) && (
        <header className="card-header">
          {title ? <h2>{title}</h2> : <span />}
          {actions ? <div className="row">{actions}</div> : null}
        </header>
      )}
      {children}
    </section>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children ? <p className="muted">{children}</p> : null}
    </div>
  );
}

export function Callout({
  kind = "info",
  title,
  children,
}: {
  kind?: "info" | "warn" | "error" | "success";
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`callout ${kind}`}>
      {title ? <strong>{title}</strong> : null}
      {children ? <div>{children}</div> : null}
    </div>
  );
}

export function Toasts() {
  const { notices, dismiss } = useApp();
  if (!notices.length) return null;
  return (
    <div className="toasts" role="status" aria-live="polite">
      {notices.map((notice) => (
        <div key={notice.id} className={`toast ${notice.kind}`}>
          <div>
            <strong>{notice.message}</strong>
            {notice.hint ? <p>{notice.hint}</p> : null}
          </div>
          <button type="button" className="icon-btn" onClick={() => dismiss(notice.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
