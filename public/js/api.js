// Minimal API helper. Token is kept in localStorage for simplicity in this
// scaffold; for production, prefer an HttpOnly, Secure session cookie set by
// the server so the token is never reachable from page JavaScript (XSS).
const Api = {
  base: "/api",
  token() { return localStorage.getItem("wsc_token"); },
  setToken(t) { localStorage.setItem("wsc_token", t); },
  clearToken() { localStorage.removeItem("wsc_token"); },
  setUser(u) { localStorage.setItem("wsc_user", JSON.stringify(u)); },
  user() { try { return JSON.parse(localStorage.getItem("wsc_user")); } catch { return null; } },

  async request(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (this.token()) headers.Authorization = `Bearer ${this.token()}`;
    const res = await fetch(this.base + path, { ...opts, headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  },
};

function requireAuth() {
  if (!Api.token()) window.location.href = "/login.html";
}

function requireRole(role) {
  const u = Api.user();
  if (!u || u.role !== role) window.location.href = "/login.html";
}
