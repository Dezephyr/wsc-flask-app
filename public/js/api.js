// Minimal API helper with module shortcuts.
// Token is kept in localStorage for simplicity in this scaffold; for production,
// prefer an HttpOnly, Secure session cookie set by the server so the token is
// never reachable from page JavaScript (XSS).

const Api = {
  base: "/api",

  token() { return localStorage.getItem("wsc_token"); },
  setToken(t) { localStorage.setItem("wsc_token", t); },
  clearToken() { localStorage.removeItem("wsc_token"); },
  setUser(u) { localStorage.setItem("wsc_user", JSON.stringify(u)); },
  user() { try { return JSON.parse(localStorage.getItem("wsc_user")); } catch { return null; } },

  async request(path, opts = {}) {
    const isFormData = opts.body instanceof FormData;
    const headers = Object.assign(
      isFormData ? {} : { "Content-Type": "application/json" },
      opts.headers || {}
    );
    if (this.token()) headers.Authorization = `Bearer ${this.token()}`;
    const res = await fetch(this.base + path, { ...opts, headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // Surface the server's `detail` (or `message`) so the UI shows the
      // real reason — e.g. "no such column: require_wallet_to_withdraw" —
      // instead of the generic `error` field alone.
      const msg = data.detail || data.message || data.error || `Request failed (${res.status})`;
      console.error("[api] request failed:", res.status, path, msg, data);
      throw new Error(msg);
    }
    return data;
  },

  /* ---------- Notifications ---------- */
  notifications: {
    list()      { return Api.request("/notifications"); },
    unread()    { return Api.request("/notifications/unread-count"); },
    markRead(id){ return Api.request(`/notifications/${id}/read`, { method: "POST" }); },
    markAll()   { return Api.request("/notifications/read-all",   { method: "POST" }); },
  },

  /* ---------- Wallets ---------- */
  wallets: {
    list()        { return Api.request("/wallets"); },
    link(body)    { return Api.request("/wallets", { method: "POST", body: JSON.stringify(body) }); },
    unlink(id)    { return Api.request(`/wallets/${id}`, { method: "DELETE" }); },
  },

  /* ---------- Loans ---------- */
  loans: {
    mine()        { return Api.request("/loans"); },
    submit(body)  { return Api.request("/loans", { method: "POST", body: JSON.stringify(body) }); },
  },

  /* ---------- Referrals ---------- */
  referrals: {
    mine() { return Api.request("/auth/referrals"); },
  },

  /* ---------- Preferences / password ---------- */
  prefs: {
    update(body) { return Api.request("/auth/preferences", { method: "PATCH", body: JSON.stringify(body) }); },
  },
  password: {
    change(body) { return Api.request("/auth/change-password", { method: "POST", body: JSON.stringify(body) }); },
  },
};

function requireAuth() {
  if (!Api.token()) window.location.href = "/login.html";
}

function requireRole(role) {
  const u = Api.user();
  if (!u || u.role !== role) window.location.href = "/login.html";
}