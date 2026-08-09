const API_BASE = import.meta.env.VITE_BID_WRITER_API_BASE || "";

export async function api(path, options = {}) {
  const csrf = document.cookie.split("; ").find((item) => item.startsWith("bid_writer_csrf="))?.split("=").slice(1).join("=") || "";
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}), ...(options.headers || {}) },
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  const errorMessage = typeof payload?.error === "object" ? payload.error.message : payload?.error;
  if (!response.ok) throw new Error(String(payload?.detail || errorMessage || payload || `HTTP ${response.status}`));
  if (errorMessage) throw new Error(String(errorMessage));
  return payload;
}

export const post = (path, body = {}) => api(path, { method: "POST", body: JSON.stringify(body) });
export const patch = (path, body = {}) => api(path, { method: "PATCH", body: JSON.stringify(body) });

export async function waitForJob(job, { interval = 800, timeout = 30 * 60 * 1000, onProgress } = {}) {
  if (!job?.job_type || !job?.id) return job;
  const started = Date.now();
  let current = job;
  while (!["completed", "failed", "cancelled"].includes(current.status)) {
    if (Date.now() - started > timeout) throw new Error("后台任务等待超时，可在任务中心继续查看。");
    await new Promise((resolve) => setTimeout(resolve, interval));
    current = await api(`/api/jobs/${job.id}`);
    onProgress?.(current);
  }
  if (current.status === "failed") throw new Error(current.error_message || "后台任务失败");
  if (current.status === "cancelled") throw new Error("后台任务已取消");
  return current.result || current;
}
