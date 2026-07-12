// Panel board for the server detail page.
// Each .panel wrapper can be collapsed, hidden, and dragged (by its grip)
// to reorder within or between the two columns. The arrangement is saved to
// localStorage under one global key, so it applies to every server.
//
// The bar lives in the wrapper, not the inner slot, so htmx outerHTML swaps
// of #server-players / #bindings / #migrate-card leave the chrome intact.
// All handlers are delegated on the board, so they survive those swaps too.
(function () {
  "use strict";

  var KEY = "mcontrol:dashboard:v1";
  var board = document.querySelector("[data-dashboard]");
  if (!board) return;

  var cols = Array.prototype.slice.call(board.querySelectorAll(".dashboard__col"));
  var menu = document.querySelector("[data-panels-menu]");
  var menuList = document.querySelector("[data-panels-list]");
  var resetBtn = document.querySelector("[data-panels-reset]");
  var draggingPanel = null;

  function panels() {
    return Array.prototype.slice.call(board.querySelectorAll(".panel"));
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
      columns: cols.map(function (col) {
        return Array.prototype.slice
          .call(col.querySelectorAll(":scope > .panel"))
          .map(function (p) { return p.dataset.pane; });
      }),
      collapsed: panels()
        .filter(function (p) { return p.getAttribute("data-collapsed") === "true"; })
        .map(function (p) { return p.dataset.pane; }),
      hidden: panels()
        .filter(function (p) { return p.hidden; })
        .map(function (p) { return p.dataset.pane; })
    };
  }

  function persist() {
    try {
      localStorage.setItem(KEY, JSON.stringify(readLayout()));
    } catch (_) {}
  }

  // Restore a saved layout. Panes missing from the saved state (e.g. the
  // legacy Migrate pane on a scaffolded server) keep their server-rendered
  // slot; unknown saved ids are ignored.
  function applyState() {
    var state = readState();
    if (!state) return;

    var byId = {};
    panels().forEach(function (p) { byId[p.dataset.pane] = p; });

    if (Array.isArray(state.columns)) {
      state.columns.forEach(function (ids, i) {
        var col = cols[i];
        if (!col || !Array.isArray(ids)) return;
        ids.forEach(function (id) {
          if (byId[id]) col.appendChild(byId[id]);
        });
      });
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
  }

  // ---- Collapse / hide (delegated click) ---------------------------------
  board.addEventListener("click", function (e) {
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
    cols.forEach(function (c) { c.classList.remove("dashboard__col--drop"); });
    persist();
  });

  function dragAfter(col, y) {
    var items = Array.prototype.slice.call(
      col.querySelectorAll(":scope > .panel:not(.panel--dragging)")
    );
    var closest = null;
    var closestOffset = -Infinity;
    items.forEach(function (child) {
      var box = child.getBoundingClientRect();
      var offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closestOffset) {
        closestOffset = offset;
        closest = child;
      }
    });
    return closest;
  }

  cols.forEach(function (col) {
    col.addEventListener("dragover", function (e) {
      if (!draggingPanel) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
      col.classList.add("dashboard__col--drop");
      var after = dragAfter(col, e.clientY);
      if (after == null) col.appendChild(draggingPanel);
      else col.insertBefore(draggingPanel, after);
    });
    col.addEventListener("dragleave", function (e) {
      if (e.relatedTarget && col.contains(e.relatedTarget)) return;
      col.classList.remove("dashboard__col--drop");
    });
    col.addEventListener("drop", function (e) {
      // Reorder already happened during dragover; cancel the browser's default
      // drop so the dragged pane id isn't inserted into an input / the editor
      // when the drag is released over an editable descendant.
      if (draggingPanel) e.preventDefault();
    });
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
