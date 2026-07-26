const API_BASE = "";

/**
 * Wraps fetch with credentials included (so the session cookie is sent) and
 * JSON handling. Throws an Error with a readable message on failure.
 * Dispatches a "ppe:unauthorized" event on 401 so the app can show the
 * login screen from one place.
 */
async function apiFetch(path, options = {}) {
  const opts = {
    ...options,
    credentials: "include",
    headers: {
      ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  };
  const res = await fetch(`${API_BASE}${path}`, opts);

  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent("ppe:unauthorized"));
    throw new Error("Not authenticated");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch (e) {
      /* ignore parse errors */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return res.json();
  }
  return res;
}

async function apiGetJSON(path) {
  return apiFetch(path, { method: "GET" });
}

async function apiPostJSON(path, body) {
  return apiFetch(path, { method: "POST", body: JSON.stringify(body) });
}
