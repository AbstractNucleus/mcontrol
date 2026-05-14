// Lifecycle-button a11y helpers (issue #110, decision 039).
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
  // carries `data-state` reflecting the new server state. htmx fires
  // `htmx:oobAfterSwap` against the newly-inserted node, so we read the
  // state off it and write a short sentence into the aria-live region.
  document.body.addEventListener("htmx:oobAfterSwap", (evt) => {
    const target = evt.detail && evt.detail.target;
    if (!target || target.id !== "lifecycle-buttons") return;
    const status = document.getElementById("lifecycle-status");
    if (!status) return;
    const state = target.getAttribute("data-state") || "unknown";
    status.textContent = `Server state: ${state}.`;
  });
})();
