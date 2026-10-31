import type { Approval } from "../lib/types";
import { titleCase } from "../lib/format";

interface Props {
  approval: Approval;
  busy?: boolean;
  onDecide: (approved: boolean) => void;
}

const RISK_LABEL: Record<string, string> = {
  low: "Low risk",
  medium: "Needs review",
  high: "High risk",
};

export function ApprovalCard({ approval, busy = false, onDecide }: Props) {
  const risk = approval.risk || "low";
  return (
    <section className={`approval-card risk-${risk}`} aria-label="Approval required">
      <header>
        <span className="badge badge-warn">Approval required</span>
        <span className="badge">{titleCase(approval.action)}</span>
        <span className={`badge badge-${risk}`}>{RISK_LABEL[risk] ?? risk}</span>
      </header>
      <h4>{approval.title || approval.action}</h4>
      {approval.target ? (
        <p className="approval-target">
          <strong>Target:</strong> {approval.target}
        </p>
      ) : null}
      {approval.description ? <p>{approval.description}</p> : null}
      {approval.cost ? (
        <p>
          <strong>Cost:</strong> {approval.cost}
        </p>
      ) : null}
      {approval.consequences ? <p className="muted">{approval.consequences}</p> : null}
      {approval.status !== "pending" ? (
        <p className="muted">Status: {approval.status}</p>
      ) : (
        <div className="row">
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={() => onDecide(true)}
          >
            Approve and run
          </button>
          <button
            type="button"
            className="btn ghost"
            disabled={busy}
            onClick={() => onDecide(false)}
          >
            Reject
          </button>
        </div>
      )}
    </section>
  );
}
