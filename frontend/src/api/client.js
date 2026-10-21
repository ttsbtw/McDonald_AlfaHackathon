const API_ROOT = import.meta.env.VITE_API_URL || "/api/v1";
const TOKEN_KEY = "credit-cabinet-token";

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail?.message || "Не удалось выполнить запрос");
    this.name = "ApiError";
    this.status = status;
    this.code = detail?.code || "REQUEST_FAILED";
    this.fields = detail?.fields || [];
  }
}

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof URLSearchParams)) {
    headers.set("Content-Type", "application/json");
  }

  let response;
  try {
    response = await fetch(`${API_ROOT}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, {
      code: "NETWORK_ERROR",
      message: "Сервер недоступен. Проверьте, что backend запущен.",
    });
  }

  if (response.status === 204) return null;
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) {
      clearToken();
      window.dispatchEvent(new Event("auth-expired"));
    }
    throw new ApiError(response.status, payload?.error || (response.status >= 500 ? {
      code: "SERVER_UNAVAILABLE",
      message: "Сервер временно недоступен. Попробуйте ещё раз после запуска backend.",
    } : null));
  }
  return payload;
}

export const api = {
  async login(username, password) {
    const body = new URLSearchParams({ username, password });
    const result = await request("/auth/login", { method: "POST", body });
    sessionStorage.setItem(TOKEN_KEY, result.access_token);
    return result;
  },
  me: () => request("/auth/me"),
  company: () => request("/company"),
  products: () => request("/products"),
  applications: () => request("/applications?limit=100&offset=0"),
  application: (id) => request(`/applications/${id}`),
  createApplication: (data) => request("/applications", {
    method: "POST",
    body: JSON.stringify(data),
  }),
  updateApplication: (id, data) => request(`/applications/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  }),
  // These routes are part of issue #5. Keeping them isolated here lets the
  // employee UI integrate without inventing fallback data or fake decisions.
  submitApplication: (id) => request(`/applications/${id}/submit`, { method: "POST" }),
  applicationEvents: (id) => request(`/applications/${id}/events`),
  bankApplications: (status = "") => request(`/bank/applications${status ? `?status=${status}` : ""}`),
  bankApplication: (id) => request(`/bank/applications/${id}`),
  bankAssessments: (id) => request(`/bank/applications/${id}/assessments`),
  requestInfo: (id, data) => request(`/bank/applications/${id}/request-info`, {
    method: "POST",
    body: JSON.stringify(data),
  }),
  decide: (id, data) => request(`/bank/applications/${id}/decision`, {
    method: "POST",
    body: JSON.stringify(data),
  }),
};
