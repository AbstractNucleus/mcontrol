// Sidebar UX — Claude Code-style resizable + collapsible left rail.
// State persists across reloads via localStorage:
//   "sidebar-width"     — px string with units (e.g. "280px")
//   "sidebar-collapsed" — "1" when collapsed; absent otherwise
// First-paint application happens inline in base.html so the rail comes
// up at the right size without a flash. This script wires the live drag
// + collapse interactions.
(function () {
  "use strict";

  var WIDTH_KEY = "sidebar-width";
  var COLLAPSED_KEY = "sidebar-collapsed";
  var MIN = 200;
  var MAX = 420;

  function setRoot(prop, value) {
    document.documentElement.style.setProperty(prop, value);
  }

  function setWidth(px) {
    var clamped = Math.max(MIN, Math.min(MAX, px));
    setRoot("--sidebar-width", clamped + "px");
    try { localStorage.setItem(WIDTH_KEY, clamped + "px"); } catch (_) {}
  }

  function isCollapsed() {
    return document.documentElement.getAttribute("data-sidebar") === "collapsed";
  }

  function setCollapsed(collapsed) {
    var root = document.documentElement;
    if (collapsed) {
      root.setAttribute("data-sidebar", "collapsed");
      try { localStorage.setItem(COLLAPSED_KEY, "1"); } catch (_) {}
    } else {
      root.removeAttribute("data-sidebar");
      try { localStorage.removeItem(COLLAPSED_KEY); } catch (_) {}
    }
  }

  function initResize() {
    var handle = document.querySelector("[data-sidebar-resize]");
    if (!handle) return;

    var dragging = false;
    var startX = 0;
    var startWidth = 0;

    handle.addEventListener("mousedown", function (evt) {
      if (isCollapsed()) return;
      dragging = true;
      startX = evt.clientX;
      var sidebar = document.querySelector(".sidebar");
      startWidth = sidebar ? sidebar.offsetWidth : 248;
      document.documentElement.setAttribute("data-sidebar-resizing", "true");
      evt.preventDefault();
    });

    document.addEventListener("mousemove", function (evt) {
      if (!dragging) return;
      setWidth(startWidth + (evt.clientX - startX));
    });

    document.addEventListener("mouseup", function () {
      if (!dragging) return;
      dragging = false;
      document.documentElement.removeAttribute("data-sidebar-resizing");
    });

    // Double-click resets to the default width. Cheap escape hatch for
    // users who've dragged into a weird state.
    handle.addEventListener("dblclick", function () {
      if (isCollapsed()) return;
      try { localStorage.removeItem(WIDTH_KEY); } catch (_) {}
      document.documentElement.style.removeProperty("--sidebar-width");
    });
  }

  function initCollapse() {
    var btn = document.querySelector("[data-sidebar-collapse]");
    if (!btn) return;
    btn.addEventListener("click", function () {
      setCollapsed(!isCollapsed());
    });
  }

  function init() {
    initResize();
    initCollapse();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
