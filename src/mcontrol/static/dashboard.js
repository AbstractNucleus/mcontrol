// Panel board for the server detail page.
// Panes tile into 1 or 2 columns responsively (CSS grid); each .panel wrapper
// can be collapsed, hidden, and dragged (by its grip) to reorder within the
// single flow. The order is saved to localStorage under one global key, so it
// applies to every server.
//
// The bar lives in the wrapper, not the inner slot, so htmx outerHTML swaps
// of #server-players / #bindings / #migrate-card leave the chrome intact.
// All handlers are delegated on the board, so they survive those swaps too.
(function () {
  "use strict";

  var KEY = "mcontrol:dashboard:v2";
  var board = document.querySelector("[data-dashboard]");
  if (!board) return;

  var menu = document.querySelector("[data-panels-menu]");
  var menuList = document.querySelector("[data-panels-list]");
  var resetBtn = document.querySelector("[data-panels-reset]");
  var draggingPanel = null;

  function panels() {
    return Array.prototype.slice.call(board.querySelectorAll(":scope > .panel"));
  }

  function readState() {
    try {
      return JSON.parse(localStorage.getItem(KEY)) || null;
    } catch (_) {
      return null;
    }
  }

  function readLayout() {
    return {
      order: panels().map(function (p) { return p.dataset.pane; }),
      collapsed: panels()
        .filter(function (p) { return p.getAttribute("data-collapsed") === "true"; })
        .map(function (p) { return p.dataset.pane; }),
      hidden: panels()
        .filter(function (p) { return p.hidden; })
        .map(function (p) { return p.dataset.pane; }),
      full: panels()
        .filter(function (p) { return p.getAttribute("data-fullwidth") === "true"; })
        .map(function (p) { return p.dataset.pane; })
    };
  }

  function persist() {
    try {
      localStorage.setItem(KEY, JSON.stringify(readLayout()));
    } catch (_) {}
  }

  // Restore a saved layout. Panes missing from the saved order (e.g. a newly
  // added pane, or the legacy Migrate pane on a scaffolded server) trail the
  // saved ones in their server-rendered order; unknown saved ids are ignored.
  function applyState() {
    var state = readState();
    if (!state) return;

    var byId = {};
    panels().forEach(function (p) { byId[p.dataset.pane] = p; });

    if (Array.isArray(state.order)) {
      var seen = {};
      var seq = state.order.filter(function (id) {
        if (!byId[id] || seen[id]) return false;
        seen[id] = true;
        return true;
      });
      panels().forEach(function (p) {
        if (!seen[p.dataset.pane]) seq.push(p.dataset.pane);
      });
      seq.forEach(function (id) { board.appendChild(byId[id]); });
    }
    (state.collapsed || []).forEach(function (id) {
      var p = byId[id];
      if (!p) return;
      p.setAttribute("data-collapsed", "true");
      var btn = p.querySelector(".panel__collapse");
      if (btn) btn.setAttribute("aria-expanded", "false");
    });
    (state.hidden || []).forEach(function (id) {
      if (byId[id]) byId[id].hidden = true;
    });
    (state.full || []).forEach(function (id) {
      var p = byId[id];
      if (!p) return;
      p.setAttribute("data-fullwidth", "true");
      var btn = p.querySelector(".panel__fullwidth");
      if (btn) btn.setAttribute("aria-pressed", "true");
    });
  }

  // ---- Collapse / hide (delegated click) ---------------------------------
  board.addEventListener("click", function (e) {
    var fullBtn = e.target.closest(".panel__fullwidth");
    if (fullBtn) {
      var fp = fullBtn.closest(".panel");
      var full = fp.getAttribute("data-fullwidth") === "true";
      fp.setAttribute("data-fullwidth", full ? "false" : "true");
      fullBtn.setAttribute("aria-pressed", full ? "false" : "true");
      persist();
      return;
    }
    var collapseBtn = e.target.closest(".panel__collapse");
    if (collapseBtn) {
      var cp = collapseBtn.closest(".panel");
      var collapsed = cp.getAttribute("data-collapsed") === "true";
      cp.setAttribute("data-collapsed", collapsed ? "false" : "true");
      collapseBtn.setAttribute("aria-expanded", collapsed ? "true" : "false");
      persist();
      return;
    }
    var hideBtn = e.target.closest(".panel__hide");
    if (hideBtn) {
      hideBtn.closest(".panel").hidden = true;
      persist();
    }
  });

  // ---- Drag to reorder (native HTML5 DnD, initiated from the grip) --------
  // draggable is toggled on only while the mouse is down on a grip, so the
  // rest of the panel (console text, inputs) stays selectable.
  function clearArmed() {
    if (draggingPanel) return; // a real drag ends via dragend
    board.querySelectorAll('.panel[draggable="true"]').forEach(function (p) {
      p.removeAttribute("draggable");
    });
  }

  board.addEventListener("mousedown", function (e) {
    if (e.button !== 0) return; // primary button only
    var grip = e.target.closest(".panel__grip");
    if (grip) {
      var panel = grip.closest(".panel");
      if (panel) panel.setAttribute("draggable", "true");
    }
  });

  // dragend clears the flag after a real drag; these cover the
  // click-without-drag and focus-lost-mid-press paths so it can't stick true
  // (a stuck flag would turn a later text-selection drag into a panel drag).
  document.addEventListener("mouseup", clearArmed);
  window.addEventListener("blur", clearArmed);

  board.addEventListener("dragstart", function (e) {
    var panel = e.target.closest(".panel");
    if (!panel || panel.getAttribute("draggable") !== "true") {
      e.preventDefault(); // not started from a grip
      return;
    }
    draggingPanel = panel;
    panel.classList.add("panel--dragging");
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      // Firefox won't start a drag unless some data is set.
      try { e.dataTransfer.setData("text/plain", panel.dataset.pane || ""); } catch (_) {}
    }
  });

  board.addEventListener("dragend", function () {
    if (!draggingPanel) return;
    draggingPanel.classList.remove("panel--dragging");
    draggingPanel.removeAttribute("draggable");
    draggingPanel = null;
    persist();
  });

  // Nearest visible panel to the pointer, plus whether to drop before or after
  // it. The board is a 1-or-2 column grid whose row tops align, so a plain
  // nearest-center test with an above/left bias lands the panel where the
  // cursor reads.
  function dropTarget(x, y) {
    var best = null;
    var bestDist = Infinity;
    var before = true;
    panels().forEach(function (el) {
      if (el === draggingPanel || el.hidden) return;
      var b = el.getBoundingClientRect();
      var cx = b.left + b.width / 2;
      var cy = b.top + b.height / 2;
      var dx = x - cx;
      var dy = y - cy;
      var dist = dx * dx + dy * dy;
      if (dist < bestDist) {
        bestDist = dist;
        best = el;
        before = dy < 0 || (Math.abs(dy) <= b.height / 2 && dx < 0);
      }
    });
    return best ? { el: best, before: before } : null;
  }

  board.addEventListener("dragover", function (e) {
    if (!draggingPanel) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    var t = dropTarget(e.clientX, e.clientY);
    if (!t) {
      if (board.lastElementChild !== draggingPanel) board.appendChild(draggingPanel);
      return;
    }
    var ref = t.before ? t.el : t.el.nextSibling;
    if (ref === draggingPanel) return; // already in place
    board.insertBefore(draggingPanel, ref);
  });

  board.addEventListener("drop", function (e) {
    // Reorder already happened during dragover; cancel the browser's default
    // drop so the dragged pane id isn't inserted into an input / the editor
    // when the drag is released over an editable descendant.
    if (draggingPanel) e.preventDefault();
  });

  // ---- Panels menu (restore hidden + reset) ------------------------------
  function buildMenu() {
    if (!menuList) return;
    menuList.textContent = "";
    panels().forEach(function (panel) {
      var titleEl = panel.querySelector(".panel__title");
      var title = titleEl ? titleEl.textContent.trim() : panel.dataset.pane;
      var label = document.createElement("label");
      label.className = "detail-menu__item detail-menu__toggle";
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !panel.hidden;
      cb.addEventListener("change", function () {
        panel.hidden = !cb.checked;
        persist();
      });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(title));
      menuList.appendChild(label);
    });
  }

  function init() {
    applyState();
    if (menu) {
      menu.hidden = false; // reveal now that the board is interactive
      menu.addEventListener("toggle", function () {
        if (menu.open) buildMenu();
      });
    }
    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        try { localStorage.removeItem(KEY); } catch (_) {}
        window.location.reload();
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
