(function () {
  // Remove a toast from the DOM after its fade-out animation completes.
  document.body.addEventListener("animationend", function (e) {
    if (e.target.classList.contains("flash-msg")) {
      e.target.remove();
    }
  });
})();
