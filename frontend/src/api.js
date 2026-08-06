const API_BASE = import.meta.env.VITE_BID_WRITER_API_BASE || "";

export async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(String(payload?.detail || payload?.error || payload || `HTTP ${response.status}`));
  if (payload?.error) throw new Error(payload.error);
  return payload;
}

export const post = (path, body = {}) => api(path, { method: "POST", body: JSON.stringify(body) });
export const patch = (path, body = {}) => api(path, { method: "PATCH", body: JSON.stringify(body) });
