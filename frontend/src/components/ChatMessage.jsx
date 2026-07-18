/* ──────────────────────────────────────────────────────────────────────────────
   ChatMessage.jsx — Chat component library for Requirements Intelligence Assistant
   Components: UserBubble, AssistantBubble, TypingIndicator, FlowBadge,
               SimpleMarkdown, TicketCard, ReportCard, SourcesPanel, ApprovalCard
   ────────────────────────────────────────────────────────────────────────────── */
import React, { useState } from "react";

/* ── Simple Markdown Renderer ──────────────────────────────────────────────── */
function renderInline(str) {
  // Returns an array of React nodes from a single text line
  const parts = str.split(/(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**"))
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*"))
      return <em key={i}>{part.slice(1, -1)}</em>;
    if (part.startsWith("`") && part.endsWith("`"))
      return <code key={i} className="md-code">{part.slice(1, -1)}</code>;
    return part;
  });
}

export function SimpleMarkdown({ text }) {
  if (!text) return null;
  const lines = text.split("\n");
  const nodes = [];
  let listBuf = [];
  let key = 0;

  const flushList = () => {
    if (listBuf.length > 0) {
      nodes.push(<ul key={key++} className="md-ul">{listBuf}</ul>);
      listBuf = [];
    }
  };

  for (const line of lines) {
    const h3   = line.match(/^###\s+(.*)/);
    const h2   = line.match(/^##\s+(.*)/);
    const h1   = line.match(/^#\s+(.*)/);
    const li   = line.match(/^[-*•]\s+(.*)/);
    const bold = line.match(/^\*\*(.*)\*\*$/);
    const hr   = line.match(/^---+$/);

    if (h3) {
      flushList();
      nodes.push(<h3 key={key++} className="md-h3">{renderInline(h3[1])}</h3>);
    } else if (h2) {
      flushList();
      nodes.push(<h2 key={key++} className="md-h2">{renderInline(h2[1])}</h2>);
    } else if (h1) {
      flushList();
      nodes.push(<h1 key={key++} className="md-h1">{renderInline(h1[1])}</h1>);
    } else if (hr) {
      flushList();
      nodes.push(<hr key={key++} className="md-hr" />);
    } else if (li) {
      listBuf.push(<li key={key++} className="md-li">{renderInline(li[1])}</li>);
    } else if (line.trim() === "") {
      flushList();
    } else {
      flushList();
      nodes.push(<p key={key++} className="md-p">{renderInline(line)}</p>);
    }
  }
  flushList();
  return <div className="md-content">{nodes}</div>;
}

/* ── Flow metadata ─────────────────────────────────────────────────────────── */
const FLOW_META = {
  rag_qa:    { label: "Document Search",    sub: "Searched requirement documents",  icon: "📋", cls: "flow-rag",    desc: "Answered from BRD / requirement documents" },
  jira_qa:   { label: "Jira Lookup",        sub: "Queried live Jira data",          icon: "📌", cls: "flow-jira",   desc: "Answered from live Jira project data" },
  hybrid_qa: { label: "BRD + Jira Search",  sub: "Cross-checked docs against Jira", icon: "🔗", cls: "flow-hybrid", desc: "Cross-referenced BRD documents + live Jira" },
  ticket:    { label: "Creating Ticket",    sub: "Drafting a Jira ticket",          icon: "🎫", cls: "flow-ticket", desc: "Jira ticket draft — awaiting your approval" },
  report:    { label: "Status Report",      sub: "Generating project report",       icon: "📊", cls: "flow-report", desc: "Project status report — awaiting your approval" },
};

/* ── Flow Badge ────────────────────────────────────────────────────────────── */
export function FlowBadge({ flow }) {
  const meta = FLOW_META[flow] || { label: flow || "Processing", sub: "", icon: "⚙️", cls: "flow-default", desc: "" };
  return (
    <div className={`flow-banner ${meta.cls}`} title={meta.desc}>
      <span className="flow-banner-icon">{meta.icon}</span>
      <div className="flow-banner-text">
        <span className="flow-banner-label">{meta.label}</span>
        {meta.sub && <span className="flow-banner-sub">{meta.sub}</span>}
      </div>
    </div>
  );
}

/* ── User Bubble ───────────────────────────────────────────────────────────── */
export function UserBubble({ text }) {
  return (
    <div className="msg-row msg-row--user">
      <div className="bubble bubble--user">{text}</div>
      <div className="avatar avatar--user">U</div>
    </div>
  );
}

/* ── Typing Indicator ──────────────────────────────────────────────────────── */
export function TypingIndicator({ flow }) {
  const meta = FLOW_META[flow] || { icon: "⚙️", label: "Processing" };
  return (
    <div className="msg-row msg-row--assistant">
      <div className="avatar avatar--ai">{meta.icon}</div>
      <div className="bubble bubble--assistant bubble--typing">
        <div className="typing-dots">
          <span /><span /><span />
        </div>
        <span className="typing-label">
          {flow === "rag_qa"    ? "Searching requirement documents…"   :
           flow === "jira_qa"   ? "Querying live Jira data…"           :
           flow === "hybrid_qa" ? "Cross-checking BRD + Jira…"         :
           flow === "ticket"    ? "Drafting Jira ticket…"              :
           flow === "report"    ? "Generating status report…"          :
                                  "Thinking…"}
        </span>
      </div>
    </div>
  );
}

/* ── Sources Panel ─────────────────────────────────────────────────────────── */
function SourcesPanel({ sources }) {
  const [open, setOpen] = useState(false);
  if (!sources || sources.length === 0) return null;
  return (
    <div className="sources-panel">
      <button className="sources-toggle" onClick={() => setOpen(o => !o)}>
        <span>{open ? "▾" : "▸"}</span>
        {sources.length} source{sources.length !== 1 ? "s" : ""} referenced
      </button>
      {open && (
        <div className="sources-list">
          {sources.map((s, i) => (
            <div key={i} className={`source-item source-item--${s.source || "knowledge"}`}>
              <div className="source-title">
                <span className="source-icon">{s.source === "jira" ? "📌" : "📋"}</span>
                {s.title}
              </div>
              {s.score != null && (
                <div className="source-score">
                  score {(s.score * 100).toFixed(0)}%
                  {s.bm25_score != null && ` · bm25 ${(s.bm25_score * 100).toFixed(0)}%`}
                  {s.vector_score != null && ` · vec ${(s.vector_score * 100).toFixed(0)}%`}
                </div>
              )}
              <div className="source-excerpt">{s.content?.slice(0, 200)}{s.content?.length > 200 ? "…" : ""}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Ticket Card (inline in chat) ──────────────────────────────────────────── */
function TicketCard({ ticket }) {
  if (!ticket) return null;
  const priorityCls = `priority-${(ticket.priority || "medium").toLowerCase()}`;
  return (
    <div className="draft-card">
      <div className="draft-card-label">📋 Draft Ticket</div>
      <div className="ticket-summary">{ticket.summary}</div>
      <div className="ticket-meta">
        <span className={`ticket-badge ${priorityCls}`}>↑ {ticket.priority || "Medium"}</span>
        <span className="ticket-badge type">{ticket.issue_type || "Story"}</span>
        {(ticket.labels || []).map(l => (
          <span key={l} className="ticket-badge label">{l}</span>
        ))}
      </div>
      <div className="ticket-description">{ticket.description}</div>
      {ticket.acceptance_criteria?.length > 0 && (
        <div className="ac-section">
          <h3>Acceptance Criteria</h3>
          <ul className="ac-list">
            {ticket.acceptance_criteria.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* ── Report helpers ─────────────────────────────────────────────────────────── */
function parseReportMarkdown(markdown) {
  if (!markdown) return { title: "", sections: [] };
  const lines = markdown.split("\n");
  let title = "";
  const sections = [];
  let current = null;
  for (const line of lines) {
    if (line.startsWith("# ") && !title) {
      title = line.slice(2).trim();
    } else if (line.startsWith("## ")) {
      if (current) sections.push(current);
      current = { title: line.slice(3).trim(), lines: [] };
    } else if (current) {
      current.lines.push(line);
    }
  }
  if (current) sections.push(current);
  return { title, sections };
}

const SECTION_THEMES = [
  { keys: ["defect", "bug", "open issue"],               theme: "red",    icon: "🐛" },
  { keys: ["blocker", "risk", "impediment"],             theme: "amber",  icon: "⛔" },
  { keys: ["completed", "done", "closed", "resolved"],   theme: "green",  icon: "✅" },
  { keys: ["health", "overall", "assessment"],           theme: "teal",   icon: "💚" },
  { keys: ["next step", "action", "recommendation"],     theme: "purple", icon: "→"  },
  { keys: ["metric", "jira metric", "overview", "executive", "introduction", "summary"], theme: "blue", icon: "📋" },
];

function getSectionTheme(title) {
  const lower = title.toLowerCase();
  for (const { keys, theme, icon } of SECTION_THEMES) {
    if (keys.some(k => lower.includes(k))) return { theme, icon };
  }
  return { theme: "blue", icon: "📋" };
}

function extractNumber(text) {
  const m = text.match(/\b(\d+)\s+out\s+of\s+(\d+)\b/i)
    || text.match(/\b(\d+)\/(\d+)\b/);
  if (m) return `${m[1]}/${m[2]}`;
  const n = text.match(/\b(\d+)\s+(open|complete|closed|blocked|high|medium|critical|bug|defect|issue|item|ticket|blocker|story)\b/i);
  return n ? n[1] : null;
}

/* ── Report Card (inline in chat) ──────────────────────────────────────────── */
function ReportCard({ report }) {
  if (!report) return null;
  const markdown = report.markdown || "";
  const { title, sections } = parseReportMarkdown(markdown);
  const reportTitle = title || report.title || "Status Report";

  const projectMatch = reportTitle.match(/\b([A-Z]{2,8})\b/);
  const projectKey = projectMatch ? projectMatch[1] : "";

  const today = new Date().toLocaleDateString("en-US", {
    year: "numeric", month: "long", day: "numeric",
  });

  if (!sections.length) {
    return (
      <div className="report-card">
        <div className="report-card-header">
          <div className="report-header-row">
            <div className="report-header-inner">
              <div className="report-badge-icon">📊</div>
              <div>
                <div className="report-title">{reportTitle}</div>
                <div className="report-date">{today}</div>
              </div>
            </div>
          </div>
        </div>
        <div className="report-sections">
          <div className="report-sec report-sec--blue">
            <div className="report-sec-body">
              <SimpleMarkdown text={markdown} />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="report-card">
      <div className="report-card-header">
        <div className="report-header-row">
          <div className="report-header-inner">
            <div className="report-badge-icon">📊</div>
            <div>
              <div className="report-title">{reportTitle}</div>
              <div className="report-date">{today}</div>
            </div>
          </div>
          {projectKey && <span className="report-project-key">{projectKey}</span>}
        </div>
      </div>

      <div className="report-sections">
        {sections.map((sec, i) => {
          const { theme, icon } = getSectionTheme(sec.title);
          const body = sec.lines.join("\n").trim();
          const num = extractNumber(body);
          return (
            <div key={i} className={`report-sec report-sec--${theme}`}>
              <div className="report-sec-header">
                <span className="report-sec-icon">{icon}</span>
                <span className="report-sec-title">{sec.title}</span>
                {num && <span className="report-sec-num">{num}</span>}
              </div>
              {body && (
                <div className="report-sec-body">
                  <SimpleMarkdown text={body} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Approval Card ─────────────────────────────────────────────────────────── */
export function ApprovalCard({ response, flow, busy, onApprove, onReject }) {
  const [feedback, setFeedback] = useState("");
  if (!response || response.status !== "awaiting_approval") return null;
  return (
    <div className="approval-card">
      <div className="approval-card-header">
        <span className="approval-icon">👤</span>
        <span className="approval-title">
          {flow === "ticket" ? "Review & approve ticket creation" : "Review & approve report"}
        </span>
        <span className="pending-pulse">● AWAITING YOUR APPROVAL</span>
      </div>
      <div className="approval-note">
        {flow === "ticket"
          ? "Once approved, this ticket will be created in Jira."
          : "Once approved, this report will be finalised and exported."}
      </div>
      <textarea
        className="feedback-input"
        placeholder="Optional feedback or revision notes…"
        value={feedback}
        onChange={e => setFeedback(e.target.value)}
        rows={2}
      />
      <div className="approval-actions">
        <button className="btn-reject" disabled={busy} onClick={() => onReject(feedback)}>
          Reject
        </button>
        <button className="btn-approve" disabled={busy} onClick={() => onApprove(feedback)}>
          {busy ? "Processing…" : flow === "ticket" ? "Approve & Create Ticket →" : "Approve & Finalise Report →"}
        </button>
      </div>
    </div>
  );
}

/* ── Result Banner ─────────────────────────────────────────────────────────── */
function ResultBanner({ response }) {
  if (!response) return null;
  if (response.status === "completed") {
    const jira = response.draft?.jira;
    const exported = response.draft?.export;
    return (
      <div className="success-banner">
        <span>✓</span>
        <span>
          {jira?.key ? (
            <>Ticket created: <a href={jira.url} target="_blank" rel="noreferrer">{jira.key}</a></>
          ) : exported ? "Report finalised and exported." : "Completed successfully."}
        </span>
      </div>
    );
  }
  if (response.status === "rejected") {
    return <div className="rejected-banner">✗ Rejected — no action taken.</div>;
  }
  if (response.status === "failed") {
    return <div className="error-banner">✗ {response.error || "An error occurred."}</div>;
  }
  return null;
}

/* ── Confidence Badge ──────────────────────────────────────────────────────── */
function ConfidenceBadge({ confidence }) {
  if (!confidence) return null;
  const cls = { high: "conf-high", medium: "conf-medium", low: "conf-low" }[confidence] || "conf-medium";
  return <span className={`conf-badge ${cls}`}>{confidence} confidence</span>;
}

/* ── Assistant Bubble ──────────────────────────────────────────────────────── */
export function AssistantBubble({ response, busy, onApprove, onReject }) {
  if (!response) return null;
  const meta = FLOW_META[response.flow] || { icon: "⚙️" };
  const answer = response.answer;
  const draft = response.draft;
  const isAction = response.flow === "ticket" || response.flow === "report";

  return (
    <div className="msg-row msg-row--assistant">
      <div className="avatar avatar--ai">{meta.icon}</div>
      <div className="bubble bubble--assistant">

        {/* Header row */}
        <div className="bubble-header">
          <FlowBadge flow={response.flow} />
          {answer?.confidence && <ConfidenceBadge confidence={answer.confidence} />}
          {response.total_tokens > 0 && (
            <span className="token-count">{response.total_tokens} tokens</span>
          )}
        </div>

        {/* Q&A answer — rendered as Markdown */}
        {answer?.answer && (
          <div className="answer-body">
            <SimpleMarkdown text={answer.answer} />
          </div>
        )}

        {/* Gap analysis extras */}
        {answer?.gaps?.length > 0 && (
          <div className="gaps-section">
            <div className="gaps-label">⚠️ Identified Gaps</div>
            <ul className="gaps-list">
              {answer.gaps.map((g, i) => <li key={i}>{g}</li>)}
            </ul>
          </div>
        )}

        {/* Action flow: ticket draft */}
        {draft?.ticket && <TicketCard ticket={draft.ticket} />}

        {/* Action flow: report draft */}
        {draft?.report && <ReportCard report={draft.report} />}

        {/* Approval card */}
        {isAction && response.status === "awaiting_approval" && (
          <ApprovalCard
            response={response}
            flow={response.flow}
            busy={busy}
            onApprove={onApprove}
            onReject={onReject}
          />
        )}

        {/* Result banner (post-approval) */}
        <ResultBanner response={response} />

        {/* Sources */}
        <SourcesPanel sources={response.sources} />

        {/* Error state */}
        {response.status === "failed" && !isAction && (
          <div className="error-banner">✗ {response.error || "Failed to get an answer."}</div>
        )}
      </div>
    </div>
  );
}
