// Theme toggle.
// Tri-state: "system" | "light" | "dark". Persists to localStorage.
// The `data-theme` attribute on <html> has already been set by the inline
// bootstrap in base.html before stylesheets evaluated; this script wires
// up the segmented toggle and re-applies on change.
(function () {
  "use strict";
  var KEY = "theme";
  var media = window.matchMedia("(prefers-color-scheme: dark)");

  function readIntent() {
    try {
      var v = localStorage.getItem(KEY);
      if (v === "light" || v === "dark" || v === "system") return v;
    } catch (_) {}
    return "system";
  }

  function writeIntent(intent) {
    try { localStorage.setItem(KEY, intent); } catch (_) {}
  }

  function resolve(intent) {
    if (intent === "system") return media.matches ? "dark" : "light";
    return intent;
  }

  function apply(intent) {
    document.documentElement.setAttribute("data-theme", resolve(intent));
  }

  function syncControl(intent) {
    var inputs = document.querySelectorAll('[data-theme-toggle] input[name="theme"]');
    inputs.forEach(function (input) {
      var checked = input.value === intent;
      input.checked = checked;
      var label = input.closest("label");
      if (label) {
        label.setAttribute("aria-pressed", checked ? "true" : "false");
      }
    });
  }

  function init() {
    var intent = readIntent();
    apply(intent);
    syncControl(intent);

    document.querySelectorAll('[data-theme-toggle] input[name="theme"]').forEach(function (input) {
      input.addEventListener("change", function () {
        if (!input.checked) return;
        var next = input.value;
        writeIntent(next);
        apply(next);
        syncControl(next);
      });
    });

    // When the user picks "system", live-track OS theme changes.
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", function () {
        if (readIntent() === "system") apply("system");
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
