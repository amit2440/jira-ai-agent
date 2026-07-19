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
