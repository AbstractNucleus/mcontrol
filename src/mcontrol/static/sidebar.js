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

  function setWidth(px, persist) {
    var clamped = Math.max(MIN, Math.min(MAX, px));
    setRoot("--sidebar-width", clamped + "px");
    if (resizeHandle) resizeHandle.setAttribute("aria-valuenow", String(clamped));
    if (persist !== false) {
      try { localStorage.setItem(WIDTH_KEY, clamped + "px"); } catch (_) {}
    }
    return clamped;
  }

  function isCollapsed() {
    var attr = document.documentElement.getAttribute("data-sidebar");
    if (attr === "collapsed") return true;
    if (attr === "expanded") return false;
    return window.matchMedia("(max-width: 768px)").matches;
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
      setWidth(startWidth + (evt.clientX - startX), false);
    });

    document.addEventListener("mouseup", function () {
      if (!dragging) return;
      dragging = false;
      document.documentElement.removeAttribute("data-sidebar-resizing");
      var sidebar = document.querySelector(".sidebar");
      if (sidebar) setWidth(sidebar.offsetWidth, true);
    });

    // Double-click resets to the default width. Cheap escape hatch for
    // users who've dragged into a weird state.
    handle.addEventListener("dblclick", function () {
      if (isCollapsed()) return;
      try { localStorage.removeItem(WIDTH_KEY); } catch (_) {}
      document.documentElement.style.removeProperty("--sidebar-width");
      var sidebar = document.querySelector(".sidebar");
      if (resizeHandle) {
        resizeHandle.setAttribute(
          "aria-valuenow",
          String(sidebar ? sidebar.offsetWidth : 248)
        );
      }
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
    var mq = window.matchMedia("(max-width: 768px)");
    var onMq = function () { syncCollapseBtn(isCollapsed()); };
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", onMq);
    }
  }

  function initMobileDrawer() {
    var menu = document.querySelector("[data-mobile-menu]");
    var sidebar = document.querySelector("#primary-sidebar");
    var backdrop = document.querySelector("[data-close-nav]");
    var main = document.querySelector("#main");
    if (!menu || !sidebar || !backdrop || !main) return;

    function setOpen(open) {
      document.documentElement.dataset.mobileNav = String(open);
      backdrop.hidden = !open;
      menu.setAttribute("aria-expanded", String(open));
      main.inert = open;
      if (open) {
        var firstLink = sidebar.querySelector("a");
        if (firstLink) firstLink.focus();
      } else {
        menu.focus();
      }
    }

    menu.addEventListener("click", function () {
      setOpen(menu.getAttribute("aria-expanded") !== "true");
    });
    backdrop.addEventListener("click", function () { setOpen(false); });
    document.addEventListener("keydown", function (event) {
      if (document.documentElement.dataset.mobileNav !== "true") return;
      if (event.key === "Escape") {
        setOpen(false);
        event.preventDefault();
      }
      if (event.key === "Tab") {
        var items = [menu].concat(Array.from(
          sidebar.querySelectorAll("a, button, input")
        ).filter(function (element) {
          return !element.disabled && element.getClientRects().length;
        }));
        var first = items[0];
        var last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        }
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    });
    var media = window.matchMedia("(min-width: 768px)");
    var closeAtDesktop = function (event) {
      if (event.matches && document.documentElement.dataset.mobileNav === "true") {
        setOpen(false);
      }
    };
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", closeAtDesktop);
    }
  }

  function init() {
    initResize();
    initCollapse();
    initMobileDrawer();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
