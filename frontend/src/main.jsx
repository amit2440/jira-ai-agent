import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { AssistantBubble, TypingIndicator, UserBubble } from "./components/ChatMessage";
import { approveRun, sendChat } from "./services/api";
import "./style.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

const SUGGESTIONS = [
  { icon: "📋", label: "Query BRD",     text: "What does the EOMS BRD say about employee document upload requirements?" },
  { icon: "📌", label: "Jira Lookup",   text: "How many open bugs are there in the EOMS project?" },
  { icon: "🔗", label: "Gap Analysis",  text: "Are all the EOMS security requirements covered by existing Jira tickets?" },
  { icon: "🎫", label: "Draft Ticket",  text: "Create a user story for implementing a self-service Active Directory account provisioning workflow triggered automatically after HR approval." },
  { icon: "📊", label: "Status Report", text: "Provide a comprehensive project status report for the EOMS project, including open defects by severity, current blockers, completed items, and overall health assessment." },
];

const DEFAULT_PARAMS = { temperature: 0.0, maxTokens: 2000, topP: 1.0 };

/* ── Welcome Screen ──────────────────────────────────────────────────────── */
function WelcomeScreen({ onSuggestion }) {
  return (
    <div className="chat-welcome">
      <div className="welcome-icon">🧠</div>
      <div className="welcome-title">Requirements <em>Intelligence</em> Assistant</div>
      <div className="welcome-sub">
        Ask natural-language questions about Business Requirement Documents, query live Jira data,
        analyse implementation gaps, or draft delivery-ready tickets and status reports — all from one place.
      </div>
      <div className="cap-grid">
        {SUGGESTIONS.map((s) => (
          <div key={s.label} className="cap-card" onClick={() => onSuggestion(s.text)}>
            <span className="cap-card-icon">{s.icon}</span>
            <div className="cap-card-title">{s.label}</div>
            <div className="cap-card-desc">{s.text.slice(0, 72)}…</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── LangGraph Modal ─────────────────────────────────────────────────────── */
const ZOOM_STEP = 0.15;
const ZOOM_MIN  = 0.3;
const ZOOM_MAX  = 4.0;

function GraphModal({ onClose }) {
  const [mermaidGraph, setMermaidGraph] = useState("");
  const [loading, setLoading]           = useState(true);
  const [zoom, setZoom]                 = useState(1.0);
  const bodyRef                         = useRef(null);

  useEffect(() => {
    fetch(`${API}/graph`)
      .then(r => r.json())
      .then(async data => {
        if (data.mermaid) {
          if (window.mermaid) {
            try {
              const { svg } = await window.mermaid.render("graphDiv", data.mermaid);
              setMermaidGraph(svg);
            } catch {
              setMermaidGraph(`<pre style="font-size:11px;color:var(--text-muted)">${data.mermaid}</pre>`);
            }
          } else {
            setMermaidGraph(`<pre style="font-size:11px;color:var(--text-muted)">${data.mermaid}</pre>`);
          }
        } else {
          setMermaidGraph("<p>No graph data available</p>");
        }
        setLoading(false);
      })
      .catch(err => {
        setMermaidGraph(`<p style="color:var(--red)">Failed to load graph: ${err.message}</p>`);
        setLoading(false);
      });
  }, []);

  function handleWheel(e) {
    e.preventDefault();
    setZoom(z => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z - e.deltaY * 0.001)));
  }

  function zoomIn()    { setZoom(z => Math.min(ZOOM_MAX, +(z + ZOOM_STEP).toFixed(2))); }
  function zoomOut()   { setZoom(z => Math.max(ZOOM_MIN, +(z - ZOOM_STEP).toFixed(2))); }
  function zoomReset() { setZoom(1.0); }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">🔀 LangGraph Workflow — 5-Flow Architecture</div>
          <div className="zoom-controls">
            <button className="zoom-btn" onClick={zoomOut}  title="Zoom out (scroll wheel also works)">−</button>
            <span   className="zoom-pct" onClick={zoomReset} title="Reset to 100%">{Math.round(zoom * 100)}%</span>
            <button className="zoom-btn" onClick={zoomIn}   title="Zoom in">+</button>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" ref={bodyRef} onWheel={handleWheel}>
          {loading
            ? <span style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading diagram…</span>
            : (
              <div
                style={{
                  transform: `scale(${zoom})`,
                  transformOrigin: "top center",
                  transition: "transform 0.1s ease",
                  width: "100%",
                }}
                dangerouslySetInnerHTML={{ __html: mermaidGraph }}
              />
            )}
        </div>
      </div>
    </div>
  );
}

/* ── Param Badge ─────────────────────────────────────────────────────────── */
function ParamBadge({ isDefault }) {
  return (
    <span className={`param-tag ${isDefault ? "param-tag--default" : "param-tag--active"}`}>
      {isDefault ? "default" : "custom"}
    </span>
  );
}

/* ── Main App ────────────────────────────────────────────────────────────── */
function App() {
  const [messages, setMessages]     = useState([]);
  const [input, setInput]           = useState("");
  const [globalBusy, setGlobalBusy] = useState(false);
  const [darkMode, setDarkMode]     = useState(false);
  const [operatingMode, setOpMode]  = useState(null); // "demo" | "groq" | "live"
  const [showGraph, setShowGraph]   = useState(false);

  // LLM parameters (top_k removed — Groq does not support it)
  const [temperature, setTemperature] = useState(DEFAULT_PARAMS.temperature);
  const [maxTokens, setMaxTokens]     = useState(DEFAULT_PARAMS.maxTokens);
  const [topP, setTopP]               = useState(DEFAULT_PARAMS.topP);
  const [projectKey, setProjectKey]   = useState("EOMS");

  const threadRef   = useRef(null);
  const textareaRef = useRef(null);

  // Apply dark mode to document root
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", darkMode ? "dark" : "light");
  }, [darkMode]);

  // Fetch operating mode from /health on mount
  useEffect(() => {
    fetch(`${API.replace("/api", "")}/health`)
      .then(r => r.json())
      .then(data => setOpMode(data.mode))
      .catch(() => setOpMode("demo"));
  }, []);

  // Auto-scroll to latest message
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [messages]);

  function handleInput(e) {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }

  function resetParams() {
    setTemperature(DEFAULT_PARAMS.temperature);
    setMaxTokens(DEFAULT_PARAMS.maxTokens);
    setTopP(DEFAULT_PARAMS.topP);
  }

  const paramsAreDefault =
    parseFloat(temperature) === DEFAULT_PARAMS.temperature &&
    parseInt(maxTokens, 10) === DEFAULT_PARAMS.maxTokens &&
    parseFloat(topP) === DEFAULT_PARAMS.topP;

  async function submit(text) {
    const query = (text || input).trim();
    if (!query || globalBusy) return;
    if (!projectKey.trim()) {
      // Surface inline — user must set project key before querying
      setMessages(prev => [
        ...prev,
        { type: "user", text: query },
        {
          type: "assistant",
          response: {
            run_id: "", thread_id: "", flow: "rag_qa",
            status: "failed",
            error: "Project key is required. Enter a Jira project key (e.g. EOMS) in the left sidebar before sending a message.",
          },
        },
      ]);
      return;
    }

    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setGlobalBusy(true);

    setMessages(prev => [
      ...prev,
      { type: "user", text: query },
      { type: "assistant", busy: true, flow: null },
    ]);

    const payload = {
      text: query,
      project_key: projectKey,
      llm_params: {
        temperature: parseFloat(temperature),
        max_tokens:  parseInt(maxTokens, 10),
        top_p:       parseFloat(topP),
        // top_k intentionally omitted — Groq API does not support it
      },
    };

    try {
      const response = await sendChat(payload);
      setMessages(prev => {
        const next = [...prev];
        next[next.length - 1] = { type: "assistant", response };
        return next;
      });
    } catch (err) {
      setMessages(prev => {
        const next = [...prev];
        next[next.length - 1] = {
          type: "assistant",
          response: {
            run_id: "", thread_id: "", flow: "rag_qa",
            status: "failed", error: err.message,
          },
        };
        return next;
      });
    } finally {
      setGlobalBusy(false);
    }
  }

  async function handleApproval(msgIndex, approved, feedback) {
    const msg = messages[msgIndex];
    if (!msg?.response?.run_id) return;

    setMessages(prev => {
      const next = [...prev];
      next[msgIndex] = { ...next[msgIndex], approvalBusy: true };
      return next;
    });

    try {
      const updated = await approveRun(msg.response.run_id, approved, feedback);
      setMessages(prev => {
        const next = [...prev];
        next[msgIndex] = {
          ...next[msgIndex],
          approvalBusy: false,
          response: {
            ...next[msgIndex].response,
            status: updated.status,
            draft: { ...next[msgIndex].response.draft, ...(updated.result || {}) },
            error: updated.error,
          },
        };
        return next;
      });
    } catch (err) {
      setMessages(prev => {
        const next = [...prev];
        next[msgIndex] = {
          ...next[msgIndex],
          approvalBusy: false,
          response: { ...next[msgIndex].response, error: err.message },
        };
        return next;
      });
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  const hasMessages = messages.length > 0;
  const lastAssistantMsg = [...messages].reverse().find(m => m.type === "assistant" && m.response);
  const latestEvents = lastAssistantMsg?.response?.events || [];
  const lastFlow = lastAssistantMsg?.response?.flow || null;

  /* Mode badge config */
  const modeMeta = {
    live:  { label: "Live",  cls: "mode-badge--live",  title: "Groq LLM + live Jira API" },
    groq:  { label: "Groq",  cls: "mode-badge--groq",  title: "Groq LLM · demo Jira" },
    demo:  { label: "Demo",  cls: "mode-badge--demo",  title: "No API keys — template fallbacks" },
  };
  const modeInfo = modeMeta[operatingMode] || modeMeta.demo;

  const flowMeta = {
    rag_qa:    { label: "Document Search", icon: "📋", cls: "flow-rag" },
    jira_qa:   { label: "Jira Lookup",     icon: "📌", cls: "flow-jira" },
    hybrid_qa: { label: "BRD + Jira",      icon: "🔗", cls: "flow-hybrid" },
    ticket:    { label: "Creating Ticket", icon: "🎫", cls: "flow-ticket" },
    report:    { label: "Status Report",   icon: "📊", cls: "flow-report" },
  };
  const lastFlowInfo = lastFlow ? flowMeta[lastFlow] : null;

  return (
    <div id="app-shell">
      {showGraph && <GraphModal onClose={() => setShowGraph(false)} />}

      {/* ── Left Sidebar (Settings) ── */}
      <div className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <div className="sidebar-logo-icon">⚡</div>
            <span className="sidebar-logo-name">JIRA Agent</span>
          </div>
          <button
            className="theme-toggle"
            onClick={() => setDarkMode(d => !d)}
            title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
          >
            {darkMode ? "☀️" : "🌙"}
          </button>
        </div>

        {/* Model Config */}
        <div className="sidebar-section">
          <div className="sidebar-section-title">
            <span className="dot" />Model Configuration
          </div>
          {operatingMode === "demo" && (
            <div className="param-note" style={{ marginBottom: 14, borderLeftColor: "var(--amber-bd)" }}>
              Demo mode — no Groq key. LLM params have no effect; responses use template fallbacks.
            </div>
          )}

          <div className="sidebar-control">
            <div className="control-header">
              <span className="control-label">
                Temperature
                <ParamBadge isDefault={parseFloat(temperature) === DEFAULT_PARAMS.temperature} />
              </span>
              <span className="control-value">{parseFloat(temperature).toFixed(1)}</span>
            </div>
            <input
              type="range" className="control-slider"
              min="0" max="2" step="0.1"
              value={temperature} onChange={e => setTemperature(e.target.value)}
            />
          </div>

          <div className="sidebar-control">
            <div className="control-header">
              <span className="control-label">
                Max Output Tokens
                <ParamBadge isDefault={parseInt(maxTokens, 10) === DEFAULT_PARAMS.maxTokens} />
              </span>
              <span className="control-value">{maxTokens}</span>
            </div>
            <input
              type="range" className="control-slider"
              min="256" max="16000" step="256"
              value={maxTokens} onChange={e => setMaxTokens(e.target.value)}
            />
          </div>

          <div className="sidebar-control">
            <div className="control-header">
              <span className="control-label">
                Top P (nucleus)
                <ParamBadge isDefault={parseFloat(topP) === DEFAULT_PARAMS.topP} />
              </span>
              <span className="control-value">{parseFloat(topP).toFixed(2)}</span>
            </div>
            <input
              type="range" className="control-slider"
              min="0" max="1" step="0.05"
              value={topP} onChange={e => setTopP(e.target.value)}
            />
          </div>

          {/* Top K — explicitly disabled because Groq does not support it */}
          <div className="sidebar-control">
            <div className="control-header">
              <span className="control-label">
                Top K
                <span className="param-tag param-tag--disabled">unsupported</span>
              </span>
              <span className="control-value" style={{ opacity: 0.4 }}>—</span>
            </div>
            <input
              type="range" className="control-slider"
              min="1" max="100" step="1"
              value={50}
              disabled
            />
            <div className="param-note">
              Top K is not supported by the Groq API and has no effect on output.
              Nucleus sampling (Top P) is the recommended alternative.
            </div>
          </div>

          {!paramsAreDefault && (
            <button className="reset-btn" onClick={resetParams}>
              ↺ Reset to task-specific defaults
            </button>
          )}
        </div>

        {/* Target Project */}
        <div className="sidebar-section">
          <div className="sidebar-section-title">
            <span className="dot" style={{ background: "var(--cyan)" }} />Target Project
          </div>
          <div className="sidebar-control">
            <div className="control-header">
              <span className="control-label">Jira Project Key</span>
            </div>
            <input
              type="text"
              className={`control-input${!projectKey.trim() ? " control-input--error" : ""}`}
              value={projectKey} onChange={e => setProjectKey(e.target.value.toUpperCase())}
              placeholder="e.g. EOMS, DEMO"
            />
            {!projectKey.trim() && (
              <div className="control-error">Project key required before sending messages.</div>
            )}
          </div>
        </div>

        {/* Graph */}
        <div className="sidebar-section" style={{ flex: 1, display: "flex", alignItems: "flex-end" }}>
          <button className="graph-btn" onClick={() => setShowGraph(true)}>
            🔀 View LangGraph Workflow
          </button>
        </div>
      </div>

      {/* ── Chat Container ── */}
      <div className="chat-container">
        <header>
          <div
            className="header-brand"
            onClick={() => { setMessages([]); setInput(""); }}
          >
            <div className="brand-logo">⚡</div>
            <div>
              <div className="brand-name">JIRA Agent</div>
              <div className="brand-sub">Hybrid RAG · Jira Tools · Human-in-the-Loop</div>
            </div>
          </div>
          <div className="header-meta">
            {lastFlowInfo && (
              <span className={`header-flow-badge ${lastFlowInfo.cls}`} title={`Last query: ${lastFlowInfo.label}`}>
                {lastFlowInfo.icon} {lastFlowInfo.label}
              </span>
            )}
            {projectKey.trim() && (
              <span className="header-project-key" title="Active Jira project key">
                # {projectKey}
              </span>
            )}
            {operatingMode && (
              <span className={`mode-badge ${modeInfo.cls}`} title={modeInfo.title}>
                <span className="pulse" />
                {modeInfo.label}
              </span>
            )}
          </div>
        </header>

        <div className="chat-thread" ref={threadRef}>
          {!hasMessages ? (
            <WelcomeScreen onSuggestion={submit} />
          ) : (
            messages.map((msg, i) => {
              if (msg.type === "user") return <UserBubble key={i} text={msg.text} />;
              if (msg.busy) return <TypingIndicator key={i} flow={msg.flow} />;
              return (
                <AssistantBubble
                  key={i}
                  response={msg.response}
                  busy={msg.approvalBusy || false}
                  onApprove={fb => handleApproval(i, true, fb)}
                  onReject={fb => handleApproval(i, false, fb)}
                />
              );
            })
          )}
        </div>

        <div className="chat-input-area">
          {!hasMessages && (
            <div className="suggestion-chips">
              {SUGGESTIONS.map((s) => (
                <button key={s.label} className="chip" onClick={() => submit(s.text)}>
                  {s.icon} {s.label}
                </button>
              ))}
            </div>
          )}
          <div className="input-row">
            <textarea
              ref={textareaRef}
              className="chat-textarea"
              placeholder="Ask about requirements, Jira data, or request a ticket / report…"
              value={input}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              rows={1}
              disabled={globalBusy}
            />
            <button
              className="btn-send"
              disabled={!input.trim() || globalBusy}
              onClick={() => submit()}
            >
              {globalBusy ? "…" : <><span>Send</span><span className="btn-send-icon">→</span></>}
            </button>
          </div>
          <div className="input-hint">
            <span className="hint-dot" />
            Enter to send · Shift+Enter for new line · Flows auto-detected: BRD Q&A · Jira · Hybrid · Ticket · Report
          </div>
        </div>
      </div>

      {/* ── Right Sidebar (Execution Trace) ── */}
      <div className="right-sidebar">
        <div className="right-sidebar-header">
          <span className="right-sidebar-title">Execution Trace</span>
          {latestEvents.length > 0 && (
            <span className="trace-count">{latestEvents.length} events</span>
          )}
        </div>
        {latestEvents.length === 0 ? (
          <div className="trace-empty">
            <div className="trace-empty-icon">🔍</div>
            Send a message to see the agent's execution trace here.
          </div>
        ) : (
          <div className="events-list">
            {latestEvents.map((ev, i) => {
              const hasDetail = ev.detail && Object.keys(ev.detail).length > 0;
              return (
                <div key={i} className="event-item">
                  <div className={`event-indicator type-${ev.kind || "node"}`} />
                  <div className="event-content">
                    <div className="event-header">
                      <div className="event-node">{ev.node}</div>
                      {ev.duration_ms != null && (
                        <div className="event-time">{ev.duration_ms}ms</div>
                      )}
                    </div>
                    <div className="event-message">{ev.message}</div>
                    {hasDetail && (
                      <div className="event-detail">
                        {JSON.stringify(ev.detail, null, 2)}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
