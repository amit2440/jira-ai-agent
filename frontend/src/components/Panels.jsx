/* ──────────────────────────────────────────────────────────────
   Panels.jsx – Professional component library
   ────────────────────────────────────────────────────────────── */

/* ── Execution Trace Timeline ─────────────────────────────────── */
export function Timeline({ events }) {
  return (
    <div className="trace">
      {events.map((event, index) => (
        <div className={`event ${event.kind}`} key={`${event.node}-${index}`}>
          <div className="event-dot" />
          <div className="event-content">
            <div className="event-name">{event.node.replaceAll("_", " ")}</div>
            <div className="event-msg">{event.message}</div>
            <div className="event-tags">
              {event.duration_ms != null && (
                <span className="event-tag">{event.duration_ms} ms</span>
              )}
              {event.detail?.temperature != null && (
                <span className="event-tag">temp {event.detail.temperature}</span>
              )}
              {event.detail?.token_usage?.total_tokens > 0 && (
                <span className="event-tag">
                  {event.detail.token_usage.total_tokens} tokens
                </span>
              )}
              {event.detail?.documents && (
                <span className="event-tag">
                  {event.detail.documents.length} docs
                </span>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Observability Stats ──────────────────────────────────────── */
export function ObservabilityPanel({ run }) {
  if (!run) return null;
  return (
    <div className="obs-grid">
      <div className="obs-cell">
        <span>Thread</span>
        <code>{run.thread_id.slice(0, 8)}…</code>
      </div>
      <div className="obs-cell">
        <span>Router</span>
        <strong>{run.router_decision || "—"}</strong>
      </div>
      <div className="obs-cell">
        <span>Model</span>
        <strong>{run.model || "template"}</strong>
      </div>
      <div className="obs-cell">
        <span>Tokens</span>
        <strong>{run.total_tokens}</strong>
      </div>
      <div className="obs-cell">
        <span>Prompt</span>
        <strong>{run.prompt_version}</strong>
      </div>
      <div className="obs-cell">
        <span>Docs</span>
        <strong>{run.retrieved_documents?.length || 0}</strong>
      </div>
    </div>
  );
}

/* ── Ticket Preview ───────────────────────────────────────────── */
function TicketPreview({ ticket }) {
  const priorityCls = `priority-${(ticket.priority || "medium").toLowerCase()}`;
  return (
    <div className="ticket-preview">
      <div className="ticket-summary">{ticket.summary}</div>
      <div className="ticket-meta">
        <span className={`ticket-badge ${priorityCls}`}>
          ↑ {ticket.priority || "Medium"}
        </span>
        <span className="ticket-badge type">
          {ticket.issue_type || "Story"}
        </span>
        {(ticket.labels || []).map((l) => (
          <span key={l} className="ticket-badge label">{l}</span>
        ))}
      </div>
      <div className="ticket-description">{ticket.description}</div>
      {ticket.acceptance_criteria?.length > 0 && (
        <div className="ac-section">
          <h3>Acceptance criteria</h3>
          <ul className="ac-list">
            {ticket.acceptance_criteria.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* ── Report Preview ───────────────────────────────────────────── */
function ReportPreview({ report }) {
  return (
    <div className="report-preview">
      <article>{report.markdown || JSON.stringify(report, null, 2)}</article>
    </div>
  );
}

/* ── Draft Preview ────────────────────────────────────────────── */
export function DraftPreview({ run, flow }) {
  if (!run?.result) {
    return (
      <div className="empty-state">
        <div className="empty-icon">{flow === "ticket" ? "🎫" : "📊"}</div>
        <p>
          {flow === "ticket"
            ? "Generate a Jira ticket to preview it here."
            : "Generate a status report to preview it here."}
        </p>
      </div>
    );
  }

  if ("ticket" in run.result) return <TicketPreview ticket={run.result.ticket} />;
  if ("report" in run.result) return <ReportPreview report={run.result.report} />;

  return (
    <div className="empty-state">
      <div className="empty-icon">⚙️</div>
      <p>Processing…</p>
    </div>
  );
}

/* ── Approval Actions ─────────────────────────────────────────── */
export function ApprovalActions({ run, flow, onApprove, onReject, busy }) {
  if (run?.status !== "awaiting_approval") return null;
  return (
    <div className="actions">
      <button
        className="btn-reject"
        onClick={onReject}
        disabled={busy}
      >
        Reject
      </button>
      <button
        className="btn-approve"
        onClick={onApprove}
        disabled={busy}
      >
        {busy
          ? "Processing…"
          : flow === "ticket"
          ? "Approve & Create Ticket →"
          : "Approve & Finalise Report →"}
      </button>
    </div>
  );
}

/* ── Result Banner ────────────────────────────────────────────── */
export function ResultBanner({ run }) {
  if (!run) return null;

  if (run.status === "completed") {
    const jira = run.result?.jira;
    const exported = run.result?.export;
    return (
      <div className="success-banner">
        <span>✓</span>
        <span>
          {jira?.key ? (
            <>
              Ticket created:{" "}
              <a href={jira.url} target="_blank" rel="noreferrer">
                {jira.key}
              </a>
            </>
          ) : exported ? (
            "Report finalised and exported."
          ) : (
            "Approved and finalised."
          )}
        </span>
      </div>
    );
  }

  if (run.status === "failed") {
    return (
      <div className="error-banner">
        ✗ {run.error || "An unknown error occurred."}
      </div>
    );
  }

  return null;
}
