// Lifecycle-button a11y helpers (issue #110).
//
// Two small responsibilities, both keyed off the `data-lifecycle-button`
// opt-in attribute that `_lifecycle_buttons.html` puts on each of the
// three buttons (Start / Stop / Restart):
//
//   1. `aria-busy` on the clicked button while the request is in flight.
//      htmx already disables the element via `hx-disabled-elt="this"`,
//      so screen readers also need the in-flight hint that the disabled
//      attribute alone doesn't convey.
//
//   2. Announce the new server state into `#lifecycle-status` (a visually
//      -hidden aria-live region rendered by `server_detail.html`) when
//      the post-action OOB swap of `#lifecycle-buttons` lands. The fresh
//      wrapper carries the new state on `data-state`, so we read it
//      back from the just-swapped node.
//
// The module is a no-op on pages that have no `[data-lifecycle-button]`.

(function () {
  function isLifecycleBtn(el) {
    return el && el.matches && el.matches("[data-lifecycle-button]");
  }

  function currentServerName() {
    const board = document.querySelector("[data-dashboard]");
    if (board && board.dataset.server) return board.dataset.server;
    const pane = document.querySelector(".files-pane");
    return pane ? pane.dataset.serverName : null;
  }

  function syncDeleteItem(state) {
    const btn = document.querySelector("[data-delete-server]");
    if (!btn) return;
    if (state === "running") {
      btn.disabled = true;
      btn.title = "Stop the server before deleting.";
    } else {
      btn.disabled = false;
      btn.removeAttribute("title");
    }
  }

  function syncSidebarDot(name, state) {
    if (!name || !state) return;
    const href = "/servers/" + name;
    document.querySelectorAll(".sidebar__server").forEach((a) => {
      if (a.getAttribute("href") !== href) return;
      const dot = a.querySelector(".sidebar__server-dot");
      if (dot) {
        dot.className = "sidebar__server-dot sidebar__server-dot--" + state;
      }
      a.title = name + " (" + state + ")";
    });
  }

  function syncHomeSummary() {
    const summary = document.querySelector(".fleet-summary");
    if (!summary) return;
    const n = document.querySelectorAll(".server-list .state-pill--running").length;
    summary.textContent = summary.textContent.replace(/\d+ running/, n + " running");
  }

  function applyState(state, name) {
    if (!state) return;
    const server = name || currentServerName();
    syncDeleteItem(state);
    syncSidebarDot(server, state);
    syncHomeSummary();
    document.body.dispatchEvent(new CustomEvent("mc:state-changed", {
      bubbles: true,
      detail: { state: state, server: server },
    }));
  }

  document.body.addEventListener("htmx:beforeRequest", (evt) => {
    const elt = evt.detail && evt.detail.elt;
    if (isLifecycleBtn(elt)) {
      elt.setAttribute("aria-busy", "true");
    }
  });

  document.body.addEventListener("htmx:afterRequest", (evt) => {
    const elt = evt.detail && evt.detail.elt;
    if (isLifecycleBtn(elt)) {
      elt.removeAttribute("aria-busy");
    }
  });

  // The OOB swap replaces `#lifecycle-buttons` with a fresh wrapper that
  // carries `data-state` reflecting the new server state. htmx 2 fires
  // `htmx:oobAfterSwap` on the newly-inserted node (`evt.target`), so
  // we read the state off it and write a short sentence into the
  // aria-live region.
  document.body.addEventListener("htmx:oobAfterSwap", (evt) => {
    const elt = evt.target;
    if (!(elt instanceof Element) || elt.id !== "lifecycle-buttons") return;
    const status = document.getElementById("lifecycle-status");
    const state = elt.getAttribute("data-state") || "unknown";
    if (status) status.textContent = `Server state: ${state}.`;
    applyState(state);
  });

  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const t = evt.detail && evt.detail.target;
    const el = (t instanceof Element && t.classList.contains("server-card"))
      ? t
      : (evt.target instanceof Element && evt.target.classList
        && evt.target.classList.contains("server-card") ? evt.target : null);
    if (!el) return;
    const pill = el.querySelector(".state-pill");
    const nameEl = el.querySelector(".server-card__name");
    const state = pill ? (pill.dataset.state || "").trim() : "";
    const name = nameEl ? nameEl.textContent.trim() : "";
    if (state) applyState(state, name);
  });
})();
