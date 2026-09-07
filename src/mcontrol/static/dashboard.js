(function () {
  "use strict";
  const board = document.querySelector("[data-dashboard]");
  if (!board) return;
  const root = board.closest(".server-detail-layout");
  const panels = Array.from(board.querySelectorAll(":scope > [data-pane]"));
  const byId = Object.fromEntries(panels.map(p => [p.dataset.pane, p]));
  const key = "mcontrol:dashboard:v3";
  const defaults = { order: ["console", "players", "files"], hidden: [], collapsed: [],
    spans: { console: 8, players: 4, files: 12 }, heights: { console: 420, players: 420, files: 560 } };
  let editing = false, before = null, focused = null, returnFocus = null;
  const status = document.querySelector("[data-layout-status]");
  function announce(text) { status.textContent = text; }
  function read() {
    return { order: Array.from(board.children).map(p => p.dataset.pane),
      hidden: panels.filter(p => p.hidden).map(p => p.dataset.pane),
      collapsed: panels.filter(p => p.dataset.collapsed === "true").map(p => p.dataset.pane),
      spans: Object.fromEntries(panels.map(p => [p.dataset.pane, Number(p.dataset.span)])),
      heights: Object.fromEntries(panels.map(p => [p.dataset.pane, Number(p.dataset.height)])) };
  }
  function apply(state) {
    if (!state || typeof state !== "object") state = defaults;
    const order = Array.isArray(state.order) ? state.order : defaults.order;
    [...new Set([...order, ...defaults.order])].forEach(id => { if (byId[id]) board.append(byId[id]); });
    panels.forEach(p => {
      const id = p.dataset.pane;
      p.hidden = Array.isArray(state.hidden) && state.hidden.includes(id);
      p.dataset.collapsed = String(Array.isArray(state.collapsed) && state.collapsed.includes(id));
      const span = Number(state.spans?.[id]);
      p.dataset.span = [4, 6, 8, 12].includes(span) ? span : defaults.spans[id];
      const height = Number(state.heights?.[id]);
      p.dataset.height = Number.isFinite(height) && height >= 280 && height <= 900 ? height : defaults.heights[id];
      p.style.setProperty("--panel-height", p.dataset.height + "px");
      p.querySelector("[data-panel-width]").value = p.dataset.span;
      p.querySelector("[data-panel-height]").value = p.dataset.height;
      const collapse = p.querySelector(".panel__collapse");
      collapse.setAttribute("aria-expanded", String(p.dataset.collapsed !== "true"));
      collapse.textContent = p.dataset.collapsed === "true" ? "+" : "−";
      collapse.setAttribute("aria-label", (p.dataset.collapsed === "true" ? "Expand " : "Collapse ") + id);
    });
    if (panels.every(p => p.hidden)) byId.console.hidden = false;
    panels.forEach(p => {
      const check = document.querySelector(`[data-show-panel="${p.dataset.pane}"]`);
      if (check) check.checked = !p.hidden;
    });
  }
  function persist() {
    try { localStorage.setItem(key, JSON.stringify(read())); announce("Layout saved for all servers in this browser."); }
    catch (_) { announce("Layout works for this visit. Browser storage is unavailable."); }
  }
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(key));
    if (!saved) {
      const old = JSON.parse(localStorage.getItem("mcontrol:dashboard:v2"));
      if (old && typeof old === "object") saved = { ...defaults, ...old, spans: Object.fromEntries(defaults.order.map(id => [id, Array.isArray(old.full) && old.full.includes(id) ? 12 : 6])) };
    }
  } catch (_) {}
  apply(saved || defaults);
  const visibility = document.querySelector("[data-panel-visibility]");
  panels.forEach(p => {
    const label = document.createElement("label"), check = document.createElement("input");
    check.type = "checkbox"; check.dataset.showPanel = p.dataset.pane; check.checked = !p.hidden;
    label.append(check, p.querySelector(".panel__title").textContent); visibility.append(label);
  });
  function setEditing(value) {
    editing = value; root.dataset.customizing = String(value);
    document.querySelector(".layout-actions").hidden = !value;
    document.querySelector("[data-customize]").hidden = value;
    panels.forEach(p => p.querySelector(".panel__grip").draggable = value);
  }
  document.querySelector("[data-customize]").addEventListener("click", () => { before = read(); setEditing(true); document.querySelector("[data-layout-save]").focus(); });
  document.querySelector("[data-layout-save]").addEventListener("click", () => { persist(); setEditing(false); document.querySelector("[data-customize]").focus(); });
  document.querySelector("[data-layout-cancel]").addEventListener("click", () => { apply(before); setEditing(false); announce("Layout changes cancelled."); document.querySelector("[data-customize]").focus(); });
  document.querySelector("[data-layout-reset]").addEventListener("click", () => { apply(defaults); announce("Default layout restored. Save to keep it."); });
  visibility.addEventListener("change", e => {
    const panel = byId[e.target.dataset.showPanel]; if (!panel) return;
    if (!e.target.checked && panels.filter(p => !p.hidden).length === 1) { e.target.checked = true; announce("Keep at least one panel visible."); return; }
    panel.hidden = !e.target.checked;
  });
  function endFocus() {
    if (!focused) return;
    focused.classList.remove("panel--focused"); focused.hidden = focused.dataset.wasHidden === "true";
    const button = focused.querySelector("[data-panel-focus]"); button.textContent = "Focus";
    button.setAttribute("aria-label", "Focus " + focused.dataset.pane);
    root.removeAttribute("data-focused"); focused = null; returnFocus?.focus();
  }
  function focusPanel(panel, trigger) {
    if (focused === panel) { endFocus(); return; }
    endFocus(); focused = panel; returnFocus = trigger;
    panel.dataset.wasHidden = String(panel.hidden); panel.hidden = false;
    root.dataset.focused = panel.dataset.pane; panel.classList.add("panel--focused");
    const button = panel.querySelector("[data-panel-focus]"); button.textContent = "Back to workspace";
    button.setAttribute("aria-label", "Back to workspace"); button.focus();
  }
  board.addEventListener("click", e => {
    const panel = e.target.closest("[data-pane]"); if (!panel) return;
    if (e.target.closest("[data-panel-focus]")) focusPanel(panel, e.target.closest("button"));
    if (e.target.closest(".panel__collapse")) {
      const state = read(), id = panel.dataset.pane;
      state.collapsed = state.collapsed.includes(id) ? state.collapsed.filter(x => x !== id) : [...state.collapsed, id];
      apply(state); if (!editing) persist();
    }
    const move = e.target.closest("[data-move]");
    if (move && editing) {
      const state = read(), index = state.order.indexOf(panel.dataset.pane), next = index + Number(move.dataset.move);
      if (next >= 0 && next < state.order.length) { [state.order[index], state.order[next]] = [state.order[next], state.order[index]]; apply(state); move.focus(); announce("Panel moved."); }
    }
    if (e.target.closest("[data-panel-hide]") && editing) {
      if (panels.filter(p => !p.hidden).length === 1) { announce("Keep at least one panel visible."); return; }
      panel.hidden = true; const check = document.querySelector(`[data-show-panel="${panel.dataset.pane}"]`); check.checked = false; check.focus();
    }
  });
  board.addEventListener("input", e => {
    if (!editing) return;
    const panel = e.target.closest("[data-pane]"); if (!panel) return;
    if (e.target.matches("[data-panel-width]")) panel.dataset.span = e.target.value;
    if (e.target.matches("[data-panel-height]")) { panel.dataset.height = e.target.value; panel.style.setProperty("--panel-height", e.target.value + "px"); }
  });
  let dragging = null;
  board.addEventListener("dragstart", e => {
    if (!editing || !e.target.closest(".panel__grip")) return;
    dragging = e.target.closest("[data-pane]"); e.dataTransfer.setData("text/plain", dragging.dataset.pane); e.dataTransfer.effectAllowed = "move";
  });
  board.addEventListener("dragover", e => { if (dragging) e.preventDefault(); });
  board.addEventListener("drop", e => {
    if (!dragging) return; e.preventDefault(); const target = e.target.closest("[data-pane]");
    if (target && target !== dragging) board.insertBefore(dragging, target);
    dragging = null; announce("Panel moved. Save to keep this layout.");
  });
  board.addEventListener("dragend", () => { dragging = null; });
  function settings(open, trigger) {
    endFocus(); root.dataset.settings = String(open); document.getElementById("server-settings").hidden = !open;
    document.querySelectorAll("[data-settings-open]").forEach(b => b.setAttribute("aria-expanded", String(open)));
    if (open) {
      returnFocus = trigger;
      const section = document.getElementById(trigger?.dataset.settingsOpen);
      if (section) { section.tabIndex = -1; section.focus(); } else document.querySelector("[data-settings-close]").focus();
    } else returnFocus?.focus();
  }
  document.querySelectorAll("[data-settings-open]").forEach(b => b.addEventListener("click", () => settings(true, b)));
  document.querySelector("[data-settings-close]").addEventListener("click", () => settings(false));
  document.querySelectorAll("[data-focus-files]").forEach(button => button.addEventListener("click", e => focusPanel(byId.files, e.target)));
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape" || e.defaultPrevented || e.target.closest(".cm-editor, [data-modal-root]")) return;
    if (focused) endFocus(); else if (root.dataset.settings === "true") settings(false);
  });
})();
