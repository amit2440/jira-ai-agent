/* ──────────────────────────────────────────────────────────────
   Panels.jsx – Professional component library
   ────────────────────────────────────────────────────────────── */

/* ── Execution Trace Timeline ─────────────────────────────────── */

const FLOW_LABELS = {
  rag_qa:    "BRD Q&A",
  jira_qa:   "Jira Lookup",
  hybrid_qa: "Gap Analysis",
  ticket:    "Ticket Generation",
  report:    "Status Report",
};

function getEventSummary(event) {
  const { node, detail, message } = event;
  const d = detail || {};

  switch (node) {
    case "pii_validation":
      return "PII check passed";
    case "project_validation": {
      const key = d.project_key || "";
      return `Project validated${key ? `: ${key}` : ""}`;
    }
    case "router": {
      const flow = d.flow || d.reason || "";
      const label = FLOW_LABELS[flow] || flow;
      return `Intent detected: ${label}`;
    }
    case "brd_retrieval": {
      const total  = d.total  ?? d.brd_count ?? d.documents?.length ?? 0;
      const bm25   = d.bm25_count   != null ? ` · BM25: ${d.bm25_count}`   : "";
      const vec    = d.vector_count  != null ? ` · Vector: ${d.vector_count}` : "";
      return `Retrieved ${total} BRD sections${bm25}${vec}`;
    }
    case "hybrid_retrieval":
      return `Retrieved BRD + Jira data`;
    case "jira_health":
      return `Fetched Jira health metrics`;
    case "jira_search": {
      const n = d.records ?? 0;
      return `Jira search returned ${n} issues`;
    }
    case "nl_to_jql":
      return `NL → JQL: ${d.jql || "query generated"}`;
    case "requirement_enhancement":
      return "Requirement enhanced & PII redacted";
    case "ticket_retrieval":
      return "BRD context retrieved for ticket";
    case "ticket_generation":
      return "Ticket draft generated";
    case "jira_create_ticket": {
      const key = d.key || "";
      return `Ticket created in Jira${key ? `: ${key}` : ""}`;
    }
    case "planner":
      return "Report structure planned";
    case "writer": {
      const rev = d.revision != null ? ` (revision ${d.revision})` : "";
      return `Report draft written${rev}`;
    }
    case "reviewer": {
      const qs = d.quality_score != null
        ? ` · Quality: ${Math.round(d.quality_score * 100)}%`
        : "";
      return `Report reviewed${qs}`;
    }
    case "reflection_check": {
      const decision = d.decision;
      if (decision === "writer") {
        const qs = d.quality_score != null ? ` (${Math.round(d.quality_score * 100)}%)` : "";
        return `Quality too low${qs} — revising`;
      }
      return `Reflection check passed — proceeding`;
    }
    case "revision":
      return message || "Revision triggered";
    case "confidence_check": {
      const qs = d.quality_score != null
        ? `Confidence: ${Math.round(d.quality_score * 100)}%`
        : "Confidence check";
      const warn = d.quality_warning ? " — human review required" : " — auto-continue";
      return `${qs}${warn}`;
    }
    case "rag_qa_agent": {
      const conf = d.confidence;
      return conf ? `Answer generated · Confidence: ${conf}` : "BRD answer generated";
    }
    case "jira_qa_agent":
      return "Jira data answer generated";
    case "hybrid_qa_agent":
      return "Gap analysis complete";
    case "report_export": {
      const path = d.path ? ` → ${d.path.split("/").pop()}` : "";
      return `Report exported${path}`;
    }
    case "human_approval":
      return "Awaiting human approval";
    case "logging":
      return "Execution finalised";
    default:
      return message || node.replaceAll("_", " ");
  }
}

const NODE_ICONS = {
  pii_validation:          "🛡",
  project_validation:      "🔑",
  router:                  "🧭",
  brd_retrieval:           "📄",
  hybrid_retrieval:        "📄",
  jira_health:             "📊",
  jira_search:             "🔍",
  nl_to_jql:               "🔄",
  requirement_enhancement: "✏️",
  ticket_retrieval:        "📄",
  ticket_generation:       "🎫",
  jira_create_ticket:      "✅",
  planner:                 "📋",
  writer:                  "✍️",
  reviewer:                "👁",
  reflection_check:        "🔁",
  revision:                "🔁",
  confidence_check:        "📈",
  rag_qa_agent:            "💬",
  jira_qa_agent:           "💬",
  hybrid_qa_agent:         "💬",
  report_export:           "📥",
  human_approval:          "👤",
  logging:                 "📝",
};

export function Timeline({ events }) {
  return (
    <div className="trace">
      {events.map((event, index) => {
        const summary = getEventSummary(event);
        const icon    = NODE_ICONS[event.node] || "•";
        const d       = event.detail || {};
        const completionTok = d.token_usage?.completion_tokens;
        const totalTok      = d.token_usage?.total_tokens;

        return (
          <div className={`event ${event.kind}`} key={`${event.node}-${index}`}>
            <div className="event-dot" />
            <div className="event-content">
              <div className="event-summary">
                <span className="event-icon">{icon}</span>
                <span className="event-label">{summary}</span>
              </div>
              <div className="event-tags">
                {event.duration_ms != null && (
                  <span className="event-tag">{event.duration_ms} ms</span>
                )}
                {completionTok > 0 && (
                  <span className="event-tag">{completionTok} out tokens</span>
                )}
                {!completionTok && totalTok > 0 && (
                  <span className="event-tag">{totalTok} tokens</span>
                )}
                {d.temperature != null && (
                  <span className="event-tag">temp {d.temperature}</span>
                )}
              </div>
            </div>
          </div>
        );
      })}
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
