// Theme toggle: persists to localStorage, applies via <html data-theme>
(function () {
  var stored = localStorage.getItem("wsc_theme");
  var initial = stored || "dark";
  document.documentElement.setAttribute("data-theme", initial);

  window.toggleTheme = function () {
    var current = document.documentElement.getAttribute("data-theme") || "dark";
    var next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("wsc_theme", next);
  };

  // Apply on load to avoid flash — also set before DOM ready
  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme-toggle-btn");
    if (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        window.toggleTheme();
      });
    }
  });
})();
/* ============================================================
   DRAGGABLE THEME TOGGLE
   ------------------------------------------------------------
   The user can drag the toggle to any corner. When released,
   it snaps to the nearest corner. The position is saved in
   localStorage under "wsc_theme_pos" so it persists across
   page loads.
   ============================================================ */
(function () {
  "use strict";

  var btn = document.getElementById("theme-toggle-btn");
  if (!btn) return;

  var STORAGE_KEY = "wsc_theme_pos";   // "top-left" | "top-right" | "bottom-left" | "bottom-right"
  var MARGIN = 20;                     // distance from the corner in px
  var DRAG_THRESHOLD = 6;              // px moved before we treat it as a drag, not a click

  var corners = {
    "top-left":     function () { return { x: MARGIN, y: MARGIN }; },
    "top-right":    function () { return { x: window.innerWidth  - btn.offsetWidth  - MARGIN,
                                            y: MARGIN }; },
    "bottom-left":  function () { return { x: MARGIN,
                                            y: window.innerHeight - btn.offsetHeight - MARGIN }; },
    "bottom-right": function () { return { x: window.innerWidth  - btn.offsetWidth  - MARGIN,
                                            y: window.innerHeight - btn.offsetHeight - MARGIN }; }
  };

  function applyCorner(corner, animate) {
    var fn = corners[corner] || corners["top-right"];
    var pos = fn();
    if (animate) btn.classList.add("snapping");
    btn.style.left   = pos.x + "px";
    btn.style.top    = pos.y + "px";
    btn.style.right  = "auto";
    btn.style.bottom = "auto";
    if (animate) {
      setTimeout(function () { btn.classList.remove("snapping"); }, 320);
    }
  }

  function nearestCorner(x, y) {
    var cx = x + btn.offsetWidth  / 2;
    var cy = y + btn.offsetHeight / 2;
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var horiz = cx < vw / 2 ? "left" : "right";
    var vert  = cy < vh / 2 ? "top"  : "bottom";
    return vert + "-" + horiz;
  }

  // Load saved position
  var saved = "top-right";
  try { saved = localStorage.getItem(STORAGE_KEY) || "top-right"; } catch (e) {}
  applyCorner(saved, false);

  // Reposition on resize (keep it in the same corner)
  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      var current = "top-right";
      try { current = localStorage.getItem(STORAGE_KEY) || "top-right"; } catch (e) {}
      applyCorner(current, false);
    }, 120);
  });

  // ---------- Pointer drag ----------
  var startX = 0, startY = 0;
  var startLeft = 0, startTop = 0;
  var isDragging = false;
  var moved = false;

  function onPointerDown(e) {
    // Only respond to primary button / touch / pen
    if (e.pointerType === "mouse" && e.button !== 0) return;

    isDragging = true;
    moved = false;

    var rect = btn.getBoundingClientRect();
    startLeft = rect.left;
    startTop  = rect.top;
    startX = e.clientX;
    startY = e.clientY;

    btn.classList.add("dragging");
    btn.setPointerCapture(e.pointerId);

    // Prevent the click event from firing after we drag
    e.preventDefault();
  }

  function onPointerMove(e) {
    if (!isDragging) return;

    var dx = e.clientX - startX;
    var dy = e.clientY - startY;

    if (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD) {
      moved = true;
    }

    // Keep it within the viewport
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var x = Math.max(0, Math.min(startLeft + dx, vw - btn.offsetWidth));
    var y = Math.max(0, Math.min(startTop  + dy, vh - btn.offsetHeight));

    btn.style.left   = x + "px";
    btn.style.top    = y + "px";
    btn.style.right  = "auto";
    btn.style.bottom = "auto";
  }

  function onPointerUp(e) {
    if (!isDragging) return;
    isDragging = false;
    btn.classList.remove("dragging");

    try { btn.releasePointerCapture(e.pointerId); } catch (_) {}

    // If the user didn't really move, let the theme.js click handler do its thing
    if (!moved) return;

    // Snap to the nearest corner
    var rect = btn.getBoundingClientRect();
    var corner = nearestCorner(rect.left, rect.top);
    applyCorner(corner, true);

    try { localStorage.setItem(STORAGE_KEY, corner); } catch (err) {}

    // Suppress the click that follows a drag
    btn.dataset.suppressClick = "1";
    setTimeout(function () { delete btn.dataset.suppressClick; }, 400);
  }

  btn.addEventListener("pointerdown", onPointerDown);
  btn.addEventListener("pointermove", onPointerMove);
  btn.addEventListener("pointerup",   onPointerUp);
  btn.addEventListener("pointercancel", onPointerUp);

  // Block the click if the user dragged
  btn.addEventListener("click", function (e) {
    if (btn.dataset.suppressClick) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);
})();