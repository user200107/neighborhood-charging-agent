/* API 客户端：同源优先、令牌自动续期、幂等键、统一错误 */

const CONFIG = window.__APP_CONFIG__ || {};
export const API_BASE = String(CONFIG.apiBaseUrl || "").replace(/\/+$/, "");
export const APP_VERSION = CONFIG.version || "1.0.0";

const ACCESS_KEY = "nc_access_token";
const REFRESH_KEY = "nc_refresh_token";

export class ApiError extends Error {
  constructor(message, { status = 0, code = "REQUEST_FAILED", details = null, traceId = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.traceId = traceId;
  }
}

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY) || "";
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY) || "";
  },
  set(access, refresh) {
    if (access) localStorage.setItem(ACCESS_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

let refreshPromise = null;

function makeIdempotencyKey() {
  if (window.crypto?.randomUUID) return `web-${window.crypto.randomUUID()}`;
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function refreshSession() {
  if (!tokens.refresh) throw new ApiError("登录已失效", { status: 401, code: "NO_REFRESH_TOKEN" });
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);
    try {
      const response = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: tokens.refresh }),
        signal: controller.signal,
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        tokens.clear();
        window.dispatchEvent(new CustomEvent("auth:expired"));
        throw new ApiError(data.detail || "登录已失效", {
          status: response.status,
          code: data.code || "REFRESH_FAILED",
          traceId: response.headers.get("x-trace-id"),
        });
      }
      tokens.set(data.access_token, data.refresh_token);
      window.dispatchEvent(new CustomEvent("auth:refreshed", { detail: data }));
      return data;
    } finally {
      clearTimeout(timer);
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (response.status === 204) return null;
  if (contentType.includes("application/json")) {
    return response.json().catch(() => null);
  }
  return response.text();
}

export async function request(path, options = {}) {
  const {
    method = "GET",
    body = undefined,
    auth = true,
    headers = {},
    idempotencyKey = undefined,
    timeout = 25_000,
    retryOnAuth = true,
    raw = false,
  } = options;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const finalHeaders = { Accept: "application/json", ...headers };
  if (body !== undefined) finalHeaders["Content-Type"] = "application/json";
  if (auth && tokens.access) finalHeaders.Authorization = `Bearer ${tokens.access}`;
  const isWrite = ["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase());
  if (isWrite && idempotencyKey !== null) {
    finalHeaders["Idempotency-Key"] = idempotencyKey || makeIdempotencyKey();
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      credentials: "same-origin",
    });
  } catch (error) {
    clearTimeout(timer);
    if (error.name === "AbortError") {
      throw new ApiError("请求超时，请检查网络后重试", { status: 0, code: "TIMEOUT" });
    }
    throw new ApiError("网络连接失败，请确认 API 服务已启动", { status: 0, code: "NETWORK_ERROR" });
  } finally {
    clearTimeout(timer);
  }

  if (response.status === 401 && auth && retryOnAuth && !path.startsWith("/api/auth/")) {
    try {
      await refreshSession();
      return request(path, { ...options, retryOnAuth: false });
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError("登录已失效，请重新登录", { status: 401, code: "UNAUTHORIZED" });
    }
  }

  if (raw) {
    if (!response.ok) {
      const data = await parseResponse(response);
      throw new ApiError(data?.detail || "下载失败", {
        status: response.status,
        code: data?.code,
        traceId: response.headers.get("x-trace-id"),
      });
    }
    return response;
  }

  const data = await parseResponse(response);
  if (!response.ok) {
    const message = data?.detail || (typeof data === "string" && data) || "请求失败";
    throw new ApiError(message, {
      status: response.status,
      code: data?.code || "HTTP_ERROR",
      details: data?.details,
      traceId: data?.trace_id || response.headers.get("x-trace-id"),
    });
  }
  return data;
}

export const api = {
  get: (path, options = {}) => request(path, { ...options, method: "GET" }),
  post: (path, body, options = {}) => request(path, { ...options, method: "POST", body }),
  patch: (path, body, options = {}) => request(path, { ...options, method: "PATCH", body }),
  del: (path, options = {}) => request(path, { ...options, method: "DELETE" }),

  async login(payload) {
    const data = await request("/api/auth/login", {
      method: "POST",
      body: payload,
      auth: false,
      idempotencyKey: null,
    });
    tokens.set(data.access_token, data.refresh_token);
    return data;
  },

  async logout() {
    try {
      await request("/api/auth/logout", {
        method: "POST",
        body: { refresh_token: tokens.refresh },
        idempotencyKey: null,
      });
    } catch {
      /* 退出接口失败不阻塞本地清理 */
    } finally {
      tokens.clear();
    }
  },

  me: () => request("/api/auth/me"),
  dashboard: (days = 7, communityId = null) =>
    request(`/api/dashboard?days=${days}${communityId ? `&community_id=${communityId}` : ""}`),
  communities: () => request("/api/communities"),
  piles: (params = {}) => request(`/api/piles?${new URLSearchParams(clean(params))}`),
  pile: (id) => request(`/api/piles/${id}`),
  availability: (params = {}) => request(`/api/availability?${new URLSearchParams(clean(params))}`),
  orders: (params = {}) => request(`/api/orders?${new URLSearchParams(clean(params))}`),
  order: (id) => request(`/api/orders/${id}`),
  createOrder: (payload) => request("/api/orders", { method: "POST", body: payload }),
  cancelOrder: (id, reason) => request(`/api/orders/${id}/cancel`, { method: "POST", body: { reason } }),
  startOrder: (id) => request(`/api/orders/${id}/start`, { method: "POST", body: {} }),
  completeOrder: (id, payload = {}) => request(`/api/orders/${id}/complete`, { method: "POST", body: payload }),
  reservations: (params = {}) => request(`/api/reservations?${new URLSearchParams(clean(params))}`),
  createReservation: (payload) => request("/api/reservations", { method: "POST", body: payload }),
  cancelReservation: (id) => request(`/api/reservations/${id}`, { method: "DELETE" }),
  tickets: (params = {}) => request(`/api/tickets?${new URLSearchParams(clean(params))}`),
  ticket: (id) => request(`/api/tickets/${id}`),
  createTicket: (payload) => request("/api/tickets", { method: "POST", body: payload }),
  assignTicket: (id, assigneeId) => request(`/api/tickets/${id}/assign`, { method: "POST", body: { assignee_id: assigneeId } }),
  acceptTicket: (id) => request(`/api/tickets/${id}/accept`, { method: "POST", body: {} }),
  startTicket: (id) => request(`/api/tickets/${id}/start`, { method: "POST", body: {} }),
  resolveTicket: (id, resolution) => request(`/api/tickets/${id}/resolve`, { method: "POST", body: { resolution } }),
  verifyTicket: (id, testOrderId) =>
    request(`/api/tickets/${id}/verify`, { method: "POST", body: { test_order_id: Number(testOrderId) } }),
  closeTicket: (id) => request(`/api/tickets/${id}/close`, { method: "POST", body: {} }),
  cancelTicket: (id) => request(`/api/tickets/${id}/cancel`, { method: "POST", body: {} }),
  assignees: (communityId = null) =>
    request(`/api/tickets/assignees${communityId ? `?community_id=${communityId}` : ""}`),
  approvals: (params = {}) => request(`/api/approvals?${new URLSearchParams(clean(params))}`),
  approval: (id) => request(`/api/approvals/${id}`),
  approvalSummary: () => request("/api/approvals/summary"),
  createApproval: (payload) => request("/api/approvals", { method: "POST", body: payload }),
  decideApproval: (id, decision, comment = "") =>
    request(`/api/approvals/${id}/decide`, { method: "POST", body: { decision, comment } }),
  executeApproval: (id) => request(`/api/approvals/${id}/execute`, { method: "POST", body: {} }),
  agentChat: (payload) => request("/api/agent/chat", { method: "POST", body: payload, timeout: 60_000 }),
  agentSuggestions: () => request("/api/agent/suggestions"),
  agentRuns: (sessionId = null) =>
    request(`/api/agent/runs${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`),
  reports: (days = 30, communityId = null) =>
    request(`/api/reports/overview?days=${days}${communityId ? `&community_id=${communityId}` : ""}`),
  audit: (params = {}) => request(`/api/audit?${new URLSearchParams(clean(params))}`),
  auditActions: () => request("/api/audit/actions"),
  users: (params = {}) => request(`/api/users?${new URLSearchParams(clean(params))}`),
  deviceEvents: (params = {}) => request(`/api/device-events?${new URLSearchParams(clean(params))}`),

  async download(path, fallbackName = "export.csv") {
    const response = await request(path, { raw: true, timeout: 60_000 });
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const match = /filename="?([^";]+)"?/.exec(disposition);
    return { blob, filename: match?.[1] || fallbackName };
  },
};

function clean(params) {
  const out = {};
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") out[key] = value;
  });
  return out;
}
