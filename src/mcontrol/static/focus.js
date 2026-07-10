// Focus rescue after whole-card swaps. htmx 2.x restores
// focus by id when the focused element's id survives the swap; when it
// doesn't (Edit→form toggles replace the whole card), focus drops to
// <body>. If the settled content carries an [autofocus] element, move
// focus there so keyboard users aren't thrown back to the top.
(function () {
  "use strict";

  document.body.addEventListener("htmx:afterSettle", (evt) => {
    const active = document.activeElement;
    if (active && active !== document.body) return;
    const root = (evt.detail && evt.detail.elt) || evt.target;
    if (!root || root.nodeType !== 1) return;
    const el = root.matches("[autofocus]")
      ? root
      : root.querySelector("[autofocus]");
    if (el) el.focus();
  });
})();
