const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

// Skip ngrok's browser-warning interstitial when tunnelling through ngrok
const BASE_HEADERS = { "ngrok-skip-browser-warning": "true" };

/** Unified chat endpoint — auto-routes via backend LLM router. */
export async function sendChat(payload) {
  const response = await fetch(`${API}/chat`, {
    method: "POST",
    headers: { ...BASE_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

/**
 * SSE variant of sendChat. Calls onStep(event) for each `{type:"step", node, message}`
 * as a graph node completes, then resolves with the final ChatResponse (from the
 * `{type:"done", response}` event). Falls back to a plain POST + JSON parse if the
 * response isn't a stream (e.g. proxies that buffer SSE).
 */
export async function streamChat(payload, onStep) {
  const response = await fetch(`${API}/chat/stream`, {
    method: "POST",
    headers: { ...BASE_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  if (!response.body) {
    return response.json();
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResponse = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const raw of events) {
      const line = raw.split("\n").find(l => l.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6));
      if (event.type === "step") onStep?.(event);
      else if (event.type === "done") finalResponse = event.response;
    }
  }

  if (!finalResponse) throw new Error("Stream ended without a response");
  return finalResponse;
}

export async function createRun(payload) {
  const response = await fetch(`${API}/runs`, {
    method: "POST",
    headers: { ...BASE_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function fetchRun(runId) {
  const response = await fetch(`${API}/runs/${runId}`, { headers: BASE_HEADERS });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function approveRun(runId, approved, feedback = "") {
  const response = await fetch(`${API}/runs/${runId}/approve`, {
    method: "POST",
    headers: { ...BASE_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ approved, feedback }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function fetchKnowledge() {
  const response = await fetch(`${API}/knowledge`, { headers: BASE_HEADERS });
  return response.json();
}

export async function uploadKnowledge(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${API}/knowledge/upload`, {
    method: "POST",
    headers: BASE_HEADERS,
    body: formData,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
