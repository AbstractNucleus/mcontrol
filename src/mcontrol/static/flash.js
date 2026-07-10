(function () {
  // Auto-dismiss toasts 4s after they enter #flash-stack. Timer-driven
  // (not animationend) so reduced-motion users — whose animations are
  // disabled — get the same dismissal instead of toasts piling up.
  var stack = document.getElementById("flash-stack");
  if (!stack) return;

  new MutationObserver(function (records) {
    records.forEach(function (record) {
      record.addedNodes.forEach(function (node) {
        if (node.nodeType === 1 && node.classList.contains("flash-msg")) {
          setTimeout(function () { node.remove(); }, 4000);
        }
      });
    });
  }).observe(stack, { childList: true });
})();
