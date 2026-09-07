// Focus rescue after HTMX swaps. htmx 2.x restores focus by id when the
// focused element's id survives the swap; when it doesn't (Edit→form,
// lifecycle button re-render, whitelist toggle, players 422), focus
// drops to <body>. Prefer [autofocus] in the settled content, else
// restore the control that issued the request (or its equivalent).
(function () {
  "use strict";

  let pending = null;

  function snapshot() {
    const active = document.activeElement;
    if (!active || active === document.body) return null;
    const aria = active.getAttribute("aria-label") || "";
    return {
      id: active.id || "",
      name: active.getAttribute("name") || "",
      aria: aria,
      selector: active.matches("[data-lifecycle-button]") && aria
        ? `[data-lifecycle-button][aria-label="${CSS.escape(aria)}"]`
        : "",
      isEditorSave: !!(active.closest
        && active.closest("[data-file-editor-form]")
        && active.type === "submit"),
    };
  }

  function restore(root, snap) {
    if (!snap) return false;
    if (snap.isEditorSave) {
      const btn = document.querySelector("[data-file-editor-form] button[type='submit']");
      if (btn) { btn.focus(); return true; }
      const cm = document.querySelector(".file-editor__cm .cm-content");
      if (cm) { cm.focus(); return true; }
    }
    if (snap.id) {
      const byId = document.getElementById(snap.id);
      if (byId) { byId.focus(); return true; }
    }
    if (snap.selector) {
      const el = document.querySelector(snap.selector);
      if (el) { el.focus(); return true; }
    }
    if (root && root.nodeType === 1) {
      if (snap.aria) {
        const el = root.querySelector(`[aria-label="${CSS.escape(snap.aria)}"]`);
        if (el) { el.focus(); return true; }
      }
      if (snap.name) {
        const el = root.querySelector(`[name="${CSS.escape(snap.name)}"]`);
        if (el) { el.focus(); return true; }
      }
    }
    return false;
  }

  document.body.addEventListener("htmx:beforeRequest", () => {
    pending = snapshot();
  });

  document.body.addEventListener("htmx:afterSettle", (evt) => {
    const root = evt.target || (evt.detail && evt.detail.target);
    if (root && root.nodeType === 1) {
      const af = (root.matches && root.matches("[autofocus]"))
        ? root
        : (root.querySelector && root.querySelector("[autofocus]"));
      if (af) {
        af.focus();
        pending = null;
        return;
      }
    }
    const active = document.activeElement;
    if (active && active !== document.body) {
      pending = null;
      return;
    }
    if (pending) restore(root, pending);
    pending = null;
  });
})();
