// Sidebar UX. Claude Code-style resizable + collapsible left rail.
// State persists across reloads via localStorage:
//   "sidebar-width"    . px string with units (e.g. "280px")
//   "sidebar-collapsed". "1" when collapsed; absent otherwise
// First-paint application happens inline in base.html so the rail comes
// up at the right size without a flash. This script wires the live drag
// + collapse interactions.
(function () {
  "use strict";

  var WIDTH_KEY = "sidebar-width";
  var COLLAPSED_KEY = "sidebar-collapsed";
  var MIN = 200;
  var MAX = 420;
  var resizeHandle = null;

  function setRoot(prop, value) {
    document.documentElement.style.setProperty(prop, value);
  }

  function setWidth(px) {
    var clamped = Math.max(MIN, Math.min(MAX, px));
    setRoot("--sidebar-width", clamped + "px");
    if (resizeHandle) resizeHandle.setAttribute("aria-valuenow", String(clamped));
    try { localStorage.setItem(WIDTH_KEY, clamped + "px"); } catch (_) {}
    return clamped;
  }

  function isCollapsed() {
    return document.documentElement.getAttribute("data-sidebar") === "collapsed";
  }

  function syncCollapseBtn(collapsed) {
    var btn = document.querySelector("[data-sidebar-collapse]");
    if (!btn) return;
    var label = collapsed ? "Expand sidebar" : "Collapse sidebar";
    btn.setAttribute("aria-label", label);
    btn.setAttribute("title", label);
    btn.setAttribute("aria-expanded", String(!collapsed));
  }

  function setCollapsed(collapsed) {
    var root = document.documentElement;
    // Explicit "expanded" (not attribute removal): the <768px media query
    // auto-collapses unless the user has explicitly expanded.
    if (collapsed) {
      root.setAttribute("data-sidebar", "collapsed");
      try { localStorage.setItem(COLLAPSED_KEY, "1"); } catch (_) {}
    } else {
      root.setAttribute("data-sidebar", "expanded");
      try { localStorage.setItem(COLLAPSED_KEY, "0"); } catch (_) {}
    }
    syncCollapseBtn(collapsed);
  }

  function initResize() {
    var handle = document.querySelector("[data-sidebar-resize]");
    if (!handle) return;
    resizeHandle = handle;

    var sidebarEl = document.querySelector(".sidebar");
    handle.setAttribute(
      "aria-valuenow",
      String(sidebarEl ? sidebarEl.offsetWidth : 248)
    );

    handle.addEventListener("keydown", function (evt) {
      if (isCollapsed()) return;
      var sidebar = document.querySelector(".sidebar");
      var current = sidebar ? sidebar.offsetWidth : 248;
      switch (evt.key) {
        case "ArrowLeft":  setWidth(current - 16); break;
        case "ArrowRight": setWidth(current + 16); break;
        case "Home":       setWidth(MIN); break;
        case "End":        setWidth(MAX); break;
        default: return;
      }
      evt.preventDefault();
    });

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
    // Collapsed state may have been restored pre-paint by the base.html
    // bootstrap; make the button's label/expanded state agree with it.
    syncCollapseBtn(isCollapsed());
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
