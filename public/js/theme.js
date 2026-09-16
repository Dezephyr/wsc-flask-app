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