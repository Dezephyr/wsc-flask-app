/* ============================================================
   Wall Street Capital — Dashboard Shell
   Renders sidebar + top bar on every dashboard page.
   Include this in every page's <head> or before </body>.
   ============================================================ */

(function () {
  const NAV_GROUPS = [
    {
      title: "Main",
      items: [
        { label: "Portfolio Overview", href: "/dashboard.html",     icon: "home",  key: "overview" },
        { label: "Account Settings",   href: "/settings.html",      icon: "user",  key: "settings" }
      ]
    },
    {
      title: "Finance",
      items: [
        { label: "Fund Account",       href: "/fund.html",          icon: "down",  key: "fund" },
        { label: "Withdraw Funds",     href: "/withdraw.html",      icon: "up",    key: "withdraw" },
        { label: "Transaction History",href: "/history.html",       icon: "clock", key: "history" }
      ]
    },
    {
      title: "Credit & Financing",
      items: [
        { label: "Loan Application",   href: "/loans.html",         icon: "credit", key: "loans" },
        { label: "Loan History",       href: "/loans-history.html", icon: "file",   key: "loans-history" }
      ]
    },
    {
      title: "Premium Signals",
      items: [
        { label: "Premium Signals",    href: "/signals.html",       icon: "zap",   key: "signals", badge: "premium" }
      ]
    },
    {
      title: "Trading & Markets",
      items: [
        { label: "Live Markets",       href: "/markets.html",       icon: "chart", key: "markets", badge: "live" },
        { label: "Investment Plans",   href: "/plans.html",         icon: "grid",  key: "plans" },
        { label: "Stock Investment",   href: "/stock.html",         icon: "trend", key: "stock" },
        { label: "Stock Market",       href: "/stock-market.html",  icon: "bars",  key: "stock-market" },
        { label: "Crypto Trading",     href: "/crypto.html",        icon: "coin",  key: "crypto",  badge: "soon" },
        { label: "Copy Trading",       href: "/copy-trading.html",  icon: "copy",  key: "copy",    badge: "soon" },
        { label: "Internal Transfer",  href: "/transfer.html",      icon: "send",  key: "transfer",badge: "soon" },
        { label: "Bot Trading",        href: "/bot-trading.html",   icon: "bot",   key: "bot",     badge: "soon" },
        { label: "Crypto Staking",     href: "/staking.html",       icon: "lock",  key: "staking", badge: "soon" },
        { label: "Active Investments", href: "/active.html",        icon: "play",  key: "active" },
        { label: "Returns History",    href: "/returns.html",       icon: "chart", key: "returns" }
      ]
    },
    {
      title: "Services",
      items: [
        { label: "Asset Exchange",     href: "/exchange.html",      icon: "swap",  key: "exchange", badge: "soon" },
        { label: "Refer & Earn",       href: "/refer.html",         icon: "gift",  key: "refer" },
        { label: "Affiliate Program",  href: "/affiliate.html",     icon: "users", key: "affiliate" }
      ]
    }
  ];

  const ICONS = {
    home:   '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
    user:   '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    down:   '<path d="M12 3v14"/><path d="m19 10-7 7-7-7"/><path d="M5 21h14"/>',
    up:     '<path d="M12 21V7"/><path d="m5 14 7-7 7 7"/><path d="M5 3h14"/>',
    clock:  '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    credit: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
    file:   '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    zap:    '<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/>',
    chart:  '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
    grid:   '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
    trend:  '<path d="M3 17l6-6 4 4 8-8"/><path d="M17 7h4v4"/>',
    bars:   '<path d="M3 3v18h18"/><rect x="7" y="12" width="3" height="6"/><rect x="12" y="8" width="3" height="10"/><rect x="17" y="4" width="3" height="14"/>',
    coin:   '<circle cx="12" cy="12" r="9"/><path d="M12 7v10M9 9h4.5a2 2 0 0 1 0 4H9M9 13h5a2 2 0 0 1 0 4H9"/>',
    copy:   '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    send:   '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
    bot:    '<rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="8" cy="16" r="1"/><circle cx="16" cy="16" r="1"/><path d="M12 7V3"/><circle cx="12" cy="7" r="1"/>',
    lock:   '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    play:   '<polygon points="5 3 19 12 5 21 5 3"/>',
    swap:   '<path d="M7 17l-4-4 4-4"/><path d="M3 13h12a4 4 0 0 0 4-4V4"/><path d="M17 7l4 4-4 4"/>',
    gift:   '<path d="M20 12v10H4V12"/><path d="M2 7h20v5H2z"/><path d="M12 22V7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7zM12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>',
    users:  '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
  };

  function svgIcon(name) {
    const path = ICONS[name] || ICONS.home;
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + path + '</svg>';
  }

  function badgeHtml(badge) {
    if (badge === "live")    return '<span class="badge-live">Live</span>';
    if (badge === "premium") return '<span class="badge-premium">Premium</span>';
    if (badge === "soon")    return '<span class="badge-soon">Soon</span>';
    return "";
  }

  function initials(str) {
    if (!str) return "U";
    const parts = String(str).trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return parts[0].slice(0, 2).toUpperCase();
  }

  function renderSidebar(activeKey) {
    const user = (window.Api && Api.user && Api.user()) || {};
    const name = user.full_name || user.username || user.email || "User";
    const email = user.email || "";

    let nav = "";
    NAV_GROUPS.forEach(group => {
      nav += '<div class="sb-group">';
      nav += '<div class="sb-group-title">' + group.title + '</div>';
      group.items.forEach(item => {
        const active = item.key === activeKey ? " active" : "";
        nav += '<a class="sb-link' + active + '" href="' + item.href + '">' +
                 svgIcon(item.icon) +
                 '<span>' + item.label + '</span>' +
                 badgeHtml(item.badge) +
               '</a>';
      });
      nav += '</div>';
    });

    return (
      '<aside class="dash-sidebar" id="dash-sidebar">' +
        '<a class="sb-brand" href="/">' +
          '<span class="logo">W</span>' +
          '<span class="mark">Wall Street <em>Capital</em></span>' +
        '</a>' +
        '<div class="sb-user">' +
          '<div class="sb-avatar">' + initials(name) + '</div>' +
          '<div class="name">' + name + '</div>' +
          '<div class="status">Online</div>' +
          '<div class="sb-balance">' +
            '<div class="label">Balance</div>' +
            '<div class="amount" id="sb-balance-value">—</div>' +
          '</div>' +
        '</div>' +
        nav +
      '</aside>'
    );
  }

  function renderTopbar(opts) {
    const user = (window.Api && Api.user && Api.user()) || {};
    const name = user.full_name || user.username || user.email || "User";
    const email = user.email || "";
    const role = user.role || "Account Settings";
    const eyebrow = opts.eyebrow || "Overview";
    const title = opts.title || "Welcome back";

    return (
      '<header class="dash-topbar">' +
        '<div class="tb-left">' +
          '<button class="tb-burger" id="tb-burger" aria-label="Menu">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M3 12h18M3 6h18M3 18h18"/>' +
            '</svg>' +
          '</button>' +
          '<div class="tb-title-block">' +
            '<span class="tb-eyebrow">' + eyebrow + '</span>' +
            '<span class="tb-title">' + title + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="tb-right">' +
          '<span class="tb-verified">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-4z"/>' +
              '<path d="m9 12 2 2 4-4"/>' +
            '</svg>' +
            'Verified' +
          '</span>' +
          '<button class="tb-icon-btn" id="tb-notifications" aria-label="Notifications">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>' +
              '<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>' +
            '</svg>' +
            '<span class="dot"></span>' +
          '</button>' +
          '<div class="tb-user-chip" id="tb-user-chip" role="button" tabindex="0">' +
            '<div class="avatar">' + initials(name) + '</div>' +
            '<div class="meta">' +
              '<span class="name">' + name + '</span>' +
              '<span class="role">' + role + '</span>' +
            '</div>' +
            '<svg class="caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="m6 9 6 6 6-6"/>' +
            '</svg>' +
          '</div>' +
        '</div>' +
      '</header>'
    );
  }

  window.DashboardShell = {
    /**
     * Mount the shell. Call this from each page.
     * @param {Object} opts
     *   opts.activeKey  — key of the sidebar item to mark active (e.g. "overview")
     *   opts.eyebrow    — small label in the top bar (e.g. "Overview")
     *   opts.title      — larger label in the top bar (e.g. "Welcome back, Desmond")
     */
    mount: function (opts) {
      opts = opts || {};
      const app = document.getElementById("dash-app");
      if (!app) return;

      app.innerHTML =
        '<div class="sb-backdrop" id="sb-backdrop"></div>' +
        renderSidebar(opts.activeKey || "overview") +
        '<div class="dash-main">' +
          renderTopbar(opts) +
          '<main class="dash-content" id="dash-content"></main>' +
        '</div>';

      // Mobile burger
      const burger = document.getElementById("tb-burger");
      const sidebar = document.getElementById("dash-sidebar");
      const backdrop = document.getElementById("sb-backdrop");
      if (burger) {
        burger.addEventListener("click", () => {
          sidebar.classList.add("open");
          backdrop.classList.add("show");
        });
      }
      if (backdrop) {
        backdrop.addEventListener("click", () => {
          sidebar.classList.remove("open");
          backdrop.classList.remove("show");
        });
      }

      // User chip → go to settings
      const chip = document.getElementById("tb-user-chip");
      if (chip) {
        chip.addEventListener("click", () => { window.location.href = "/settings.html"; });
        chip.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            window.location.href = "/settings.html";
          }
        });
      }

      // Balance in sidebar — small fetch, best-effort
      if (window.Api && Api.token && Api.token()) {
        Api.request("/portfolio")
          .then(data => {
            const el = document.getElementById("sb-balance-value");
            if (!el) return;
            const account = data && data.account;
            if (account && account.portfolio_value) {
              el.textContent = "$" + parseFloat(account.portfolio_value).toLocaleString(undefined, {
                minimumFractionDigits: 2, maximumFractionDigits: 2
              });
            } else {
              el.textContent = "$0.00";
            }
          })
          .catch(() => {
            const el = document.getElementById("sb-balance-value");
            if (el) el.textContent = "$0.00";
          });
      }
    }
  };
})();