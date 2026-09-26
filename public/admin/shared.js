/* ============================================================
   ADMIN SHELL — shared layout, auth, and helpers
   Every /admin/*.html page includes this file.

   NOTE: `api.js` declares `const Api = {...}`, which does NOT
   attach to `window`. Always reference it as bare `Api`, never
   as `window.Api`.
   ============================================================ */

(function () {
  "use strict";

  /* ---------- Auth guard ---------- */
  if (typeof requireAuth === "function") requireAuth();

  if (typeof Api === "undefined") {
    console.error("[AdminShell] api.js did not load — cannot continue.");
    document.body.innerHTML =
      '<div style="padding:40px;color:#F87171;font-family:monospace;">' +
      'api.js failed to load. Check the network tab and reload.' +
      '</div>';
    return;
  }

  const me = (Api.user && Api.user()) || null;

  if (!me || (me.role !== "admin" && me.role !== "support")) {
    console.warn("[AdminShell] not an admin — redirecting to login.", me);
    window.location.href = "/login.html";
    return;
  }

  /* ---------- Nav config — single source of truth ---------- */
  const NAV = [
    {
      title: "Operations",
      items: [
        { key: "dashboard",     label: "Dashboard",        href: "/admin/index.html",            badgeId: null,                icon: "home" },
        { key: "kyc",           label: "KYC queue",        href: "/admin/kyc.html",              badgeId: "count-kyc",         icon: "shield-check" },
        { key: "loans",         label: "Loan review",      href: "/admin/loans.html",            badgeId: "count-loans",       icon: "credit-card" },
        { key: "withdrawals",   label: "Withdrawals",      href: "/admin/withdrawals.html",      badgeId: "count-withdrawals", icon: "send" },
        { key: "wallets",       label: "Wallet links",     href: "/admin/wallet-links.html",     badgeId: "count-wallets",     icon: "wallet" },
        { key: "traders",       label: "Copy traders",     href: "/admin/traders.html",          badgeId: "count-traders",     icon: "copy" },
        { key: "signals",       label: "Premium signals",  href: "/admin/signals.html",          badgeId: "count-signals",     icon: "zap" },
        { key: "plans",         label: "Investment plans", href: "/admin/plans.html",            badgeId: "count-plans",       icon: "grid" },
        { key: "tickets",       label: "Support tickets",  href: "/admin/tickets.html",          badgeId: "count-tickets",     icon: "message" },
        { key: "apple-signins", label: "Apple sign-ins",   href: "/admin/apple-signins.html",    badgeId: "count-apple",       icon: "apple" }
      ]
    },
    {
      title: "Configuration",
      items: [
        { key: "payment-settings", label: "Payment settings", href: "/admin/payment-settings.html", badgeId: null, icon: "credit-card" },
        { key: "login-activity",   label: "Login activity",   href: "/admin/login-activity.html",   badgeId: null, icon: "shield" },
        { key: "content",          label: "Content pages",    href: "/admin/content.html",          badgeId: null, icon: "file-text" },
        { key: "docs",             label: "Compliance docs",  href: "/admin/docs.html",             badgeId: null, icon: "file" },
        { key: "users",            label: "Users",            href: "/admin/users.html",            badgeId: "count-users", icon: "users" },
        { key: "admins",           label: "Admins",           href: "/admin/admins.html",           badgeId: null, icon: "shield" }
      ]
    }
  ];

  const ICONS = {
    "home":         '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
    "shield-check": '<path d="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-4z"/><path d="m9 12 2 2 4-4"/>',
    "credit-card":  '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
    "copy":         '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "zap":          '<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/>',
    "grid":         '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
    "message":      '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "file-text":    '<path d="M4 4h16v16H4z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "file":         '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    "users":        '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "shield":       '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "send":         '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
    "wallet":       '<rect x="2" y="6" width="20" height="14" rx="2"/><path d="M2 10h20"/><circle cx="17" cy="14" r="1"/>',
    "apple":        '<path d="M17.05 12.04c-.03-2.85 2.33-4.22 2.44-4.29-1.33-1.95-3.4-2.22-4.14-2.25-1.76-.18-3.43 1.04-4.33 1.04-.9 0-2.28-1.02-3.75-1-1.93.03-3.71 1.12-4.7 2.85-2 3.47-.51 8.61 1.44 11.43.95 1.38 2.09 2.93 3.59 2.88 1.44-.06 1.99-.93 3.73-.93 1.74 0 2.23.93 3.76.9 1.55-.03 2.53-1.4 3.48-2.78 1.1-1.6 1.55-3.15 1.57-3.23-.03-.02-3.01-1.16-3.04-4.62zM14.4 3.79c.79-.96 1.32-2.29 1.18-3.62-1.14.05-2.51.76-3.33 1.71-.73.84-1.37 2.19-1.2 3.49 1.27.1 2.57-.64 3.35-1.58z"/>'
  };

  function svgIcon(name) {
    // The Apple logo is a filled path, not a stroked one — it needs
    // fill="currentColor" and no stroke, otherwise it renders invisible.
    if (name === "apple") {
      return '<svg viewBox="0 0 24 24" fill="currentColor">' + ICONS.apple + '</svg>';
    }
    const path = ICONS[name] || ICONS["grid"];
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + path + '</svg>';
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* ---------- Sidebar HTML ---------- */
  function renderSidebar(activeKey) {
    let nav = "";
    NAV.forEach(group => {
      nav += '<div class="adm-nav-group">';
      nav += '<div class="adm-nav-title">' + group.title + '</div>';
      group.items.forEach(item => {
        const active = item.key === activeKey ? " active" : "";
        const badge = item.badgeId
          ? '<span class="badge-count" id="' + item.badgeId + '">0</span>'
          : '';
        nav += '<a class="adm-nav-link' + active + '" href="' + item.href + '">' +
                 svgIcon(item.icon) +
                 '<span>' + item.label + '</span>' +
                 badge +
               '</a>';
      });
      nav += '</div>';
    });

    return (
      '<aside class="adm-sidebar" id="adm-sidebar">' +
        '<a class="adm-brand" href="/admin/index.html">' +
          '<span class="logo">W</span>' +
          '<span class="mark">Wall Street <em>Capital</em></span>' +
        '</a>' +

        '<div class="adm-admin-pill">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-4z"/>' +
          '</svg>' +
          'Admin panel' +
        '</div>' +

        '<div class="adm-sb-user">' +
          '<div class="label">Signed in as</div>' +
          '<div class="email" id="sb-email">' + escapeHtml(me.email || "—") + '</div>' +
          '<a href="#" id="sb-logout">' +
            '<svg style="width:12px;height:12px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>' +
              '<path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>' +
            '</svg>' +
            'Log out' +
          '</a>' +
        '</div>' +

        nav +
      '</aside>'
    );
  }

  /* ---------- Topbar HTML ---------- */
  function renderTopbar() {
    return (
      '<div class="adm-topbar">' +
        '<div class="adm-tb-left">' +
          '<button class="adm-burger" id="adm-burger" aria-label="Menu">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M3 12h18M3 6h18M3 18h18"/>' +
            '</svg>' +
          '</button>' +
          '<div class="adm-tb-title" id="adm-tb-title">Administration</div>' +
        '</div>' +
        '<div class="adm-tb-right">' +
          '<span class="who" id="tb-who">' + escapeHtml(me.email || "—") + '</span>' +
          '<a href="#" id="tb-logout">Log out</a>' +
        '</div>' +
      '</div>'
    );
  }

  /* ---------- API wrapper (auto-kicks to login on 401) ---------- */
  function api(path, opts) {
    return Api.request(path, opts).catch(err => {
      const m = String(err && err.message || "");
      if (m.includes("401") || m.toLowerCase().includes("unauthorized")) {
        Api.clearToken();
        localStorage.removeItem("wsc_user");
        window.location.href = "/login.html";
      }
      throw err;
    });
  }

  /* ---------- Table auto-wrap for mobile ---------- */
  function autoWrapTables(root) {
    const container = root || document.querySelector(".adm-content");
    if (!container) return;
    const wrapOne = (tbl) => {
      if (tbl.parentElement && tbl.parentElement.classList.contains("adm-table-scroll")) return;
      const w = document.createElement("div");
      w.className = "adm-table-scroll";
      tbl.parentNode.insertBefore(w, tbl);
      w.appendChild(tbl);
    };
    container.querySelectorAll("table").forEach(wrapOne);
    const mo = new MutationObserver(muts => {
      muts.forEach(m => {
        m.addedNodes.forEach(node => {
          if (node.nodeType !== 1) return;
          if (node.tagName === "TABLE") wrapOne(node);
          node.querySelectorAll && node.querySelectorAll("table").forEach(wrapOne);
        });
      });
    });
    mo.observe(container, { childList: true, subtree: true });
  }

  /* ---------- Mount the shell ---------- */
  function mount(opts) {
    opts = opts || {};
    const app = document.getElementById("adm-app");
    if (!app) {
      console.error("[AdminShell] #adm-app not found in the DOM.");
      return;
    }

    app.innerHTML =
      renderSidebar(opts.activeKey || "") +
      '<div class="adm-backdrop" id="adm-backdrop"></div>' +
      '<main class="adm-main">' +
        renderTopbar() +
        '<div class="adm-content" id="adm-content"></div>' +
      '</main>';

    if (opts.title) {
      const t = document.getElementById("adm-tb-title");
      if (t) t.textContent = opts.title;
    }

    // Burger + backdrop wiring
    const burger = document.getElementById("adm-burger");
    const sb = document.getElementById("adm-sidebar");
    const bd = document.getElementById("adm-backdrop");
    if (burger && sb && bd) {
      burger.addEventListener("click", () => {
        sb.classList.add("open");
        bd.classList.add("show");
        document.body.classList.add("adm-sidebar-open");
      });
      bd.addEventListener("click", () => {
        sb.classList.remove("open");
        bd.classList.remove("show");
        document.body.classList.remove("adm-sidebar-open");
      });
      sb.querySelectorAll(".adm-nav-link").forEach(link => {
        link.addEventListener("click", () => {
          document.body.classList.remove("adm-sidebar-open");
        });
      });
    }

    // Logout wiring
    function doLogout(e) {
      if (e) e.preventDefault();
      Api.clearToken();
      localStorage.removeItem("wsc_user");
      window.location.href = "/login.html";
    }
    const sl = document.getElementById("sb-logout");
    const tl = document.getElementById("tb-logout");
    if (sl) sl.addEventListener("click", doLogout);
    if (tl) tl.addEventListener("click", doLogout);

    autoWrapTables();

    if (typeof opts.onReady === "function") {
      opts.onReady(document.getElementById("adm-content"));
    }
  }

  window.AdminShell = {
    mount,
    api,
    escapeHtml,
    me,
    setCount: function (id, n) {
      const el = document.getElementById(id);
      if (el) el.textContent = n;
    },
    autoWrapTables
  };
})();