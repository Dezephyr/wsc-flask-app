// ============================================================
// Wall Street Capital — theme toggle
// - Switches between dark + light modes
// - Makes the toggle draggable (persists position across pages)
// ============================================================

(function () {
  /* ---------- Theme switching ---------- */
  const KEY = "wsc_theme";
  const root = document.documentElement;

  function applyTheme(t) {
    root.setAttribute("data-theme", t);
  }

  function currentTheme() {
    return localStorage.getItem(KEY) || "dark";
  }

  applyTheme(currentTheme());

  document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("theme-toggle-btn");
    if (!btn) return;

    // ---------- Click to toggle theme ----------
    // Distinguish a click from a drag by tracking movement distance.
    let wasDragged = false;

    btn.addEventListener("click", function (e) {
      if (wasDragged) { wasDragged = false; return; }
      const next = currentTheme() === "dark" ? "light" : "dark";
      localStorage.setItem(KEY, next);
      applyTheme(next);
    });

    /* ============================================================
       Draggable behaviour
       ============================================================ */
    const POS_KEY = "wsc_theme_pos";       // stored position
    const EDGE    = 12;                    // min distance from viewport edge
    const DRAG_THRESHOLD = 4;              // px movement before it's a "drag"

    let startX = 0, startY = 0;
    let offsetX = 0, offsetY = 0;
    let dragging = false;
    let pointerId = null;

    // ---------- Restore saved position on load ----------
    function restorePosition() {
      try {
        const saved = JSON.parse(localStorage.getItem(POS_KEY));
        if (saved && typeof saved.x === "number" && typeof saved.y === "number") {
          place(saved.x, saved.y, false);
          return;
        }
      } catch (e) {}
      // No saved position — snap to bottom-right by default
      const r = btn.getBoundingClientRect();
      place(
        window.innerWidth  - r.width  - 24,
        window.innerHeight - r.height - 24,
        false
      );
    }

    // ---------- Place at (x, y) with edge clamping ----------
    function place(x, y, save = true) {
      const w = btn.offsetWidth;
      const h = btn.offsetHeight;
      const maxX = window.innerWidth  - w - EDGE;
      const maxY = window.innerHeight - h - EDGE;
      const minX = EDGE;
      const minY = EDGE;

      x = Math.max(minX, Math.min(maxX, x));
      y = Math.max(minY, Math.min(maxY, y));

      btn.style.left = x + "px";
      btn.style.top  = y + "px";
      btn.style.right = "auto";
      btn.style.bottom = "auto";

      if (save) {
        try { localStorage.setItem(POS_KEY, JSON.stringify({ x, y })); } catch (e) {}
      }
    }

    // ---------- Pointer events (works for mouse + touch + pen) ----------
    btn.addEventListener("pointerdown", function (e) {
      // Left-click only
      if (e.button !== undefined && e.button !== 0) return;

      dragging = true;
      pointerId = e.pointerId;
      wasDragged = false;
      startX = e.clientX;
      startY = e.clientY;

      const r = btn.getBoundingClientRect();
      offsetX = e.clientX - r.left;
      offsetY = e.clientY - r.top;

      btn.classList.add("dragging");
      btn.setPointerCapture && btn.setPointerCapture(e.pointerId);
    });

    btn.addEventListener("pointermove", function (e) {
      if (!dragging || e.pointerId !== pointerId) return;

      const dx = e.clientX - startX;
      const dy = e.clientY - startY;

      if (!wasDragged && Math.hypot(dx, dy) > DRAG_THRESHOLD) {
        wasDragged = true;
      }

      if (wasDragged) {
        e.preventDefault();
        place(e.clientX - offsetX, e.clientY - offsetY, false);
      }
    });

    function endDrag(e) {
      if (!dragging) return;
      dragging = false;

      btn.classList.remove("dragging");

      if (wasDragged) {
        // Snap to nearest edge horizontally (optional UX touch)
        btn.classList.add("snapping");
        const r = btn.getBoundingClientRect();
        const distLeft  = r.left;
        const distRight = window.innerWidth - r.right;
        const snapX = distLeft < distRight
          ? EDGE
          : window.innerWidth - r.width - EDGE;

        place(snapX, r.top, true);

        setTimeout(function () { btn.classList.remove("snapping"); }, 300);
      }

      if (pointerId !== null && btn.releasePointerCapture) {
        try { btn.releasePointerCapture(pointerId); } catch (e) {}
      }
      pointerId = null;
    }

    btn.addEventListener("pointerup",     endDrag);
    btn.addEventListener("pointercancel", endDrag);

    // ---------- Keep it in-bounds on window resize ----------
    window.addEventListener("resize", function () {
      const r = btn.getBoundingClientRect();
      place(r.left, r.top, true);
    });

    // ---------- Initialize ----------
    restorePosition();
  });
})();