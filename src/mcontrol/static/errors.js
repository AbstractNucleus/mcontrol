// HTMX response-error policy.
//
// 1. Swap-rescue: several endpoints answer 409 (file-save conflict, upload
//    conflict) or 422 (form validation) with an HTML partial meant for the
//    request's swap target. htmx 2.x drops 4xx responses by default, so
//    without this the re-rendered form/banner never appears. Only rescue
//    when the response is actually HTML — JSON error bodies must not be
//    injected into cards.
// 2. Anything else (500s, JSON 4xx, network failures) surfaces as an error
//    toast in #flash-stack instead of failing silently.
(function () {
  "use strict";

  document.addEventListener("htmx:beforeSwap", function (evt) {
    var xhr = evt.detail.xhr;
    if (!xhr) return;
    var status = xhr.status;
    var type = xhr.getResponseHeader("Content-Type") || "";
    if ((status === 409 || status === 422) && type.indexOf("text/html") !== -1) {
      evt.detail.shouldSwap = true;
      evt.detail.isError = false;
    }
  });

  function toast(message) {
    var stack = document.getElementById("flash-stack");
    if (!stack) return;
    var msg = document.createElement("div");
    msg.className = "flash-msg flash-msg--error";
    msg.setAttribute("role", "alert");
    var text = document.createElement("span");
    text.className = "flash-msg__text";
    text.textContent = message;
    var dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "flash-msg__dismiss";
    dismiss.setAttribute("aria-label", "Dismiss");
    dismiss.textContent = "×";
    dismiss.addEventListener("click", function () { msg.remove(); });
    msg.appendChild(text);
    msg.appendChild(dismiss);
    stack.appendChild(msg);
  }

  // Fires only when beforeSwap left isError=true, so rescued 409/422
  // responses never double-report.
  document.addEventListener("htmx:responseError", function (evt) {
    var xhr = evt.detail.xhr;
    var detail = "";
    try { detail = JSON.parse(xhr.responseText).detail || ""; } catch (_) { /* not JSON */ }
    if (typeof detail !== "string") detail = "";
    toast(detail || "Request failed (" + (xhr ? xhr.status : "?") + ")");
  });

  document.addEventListener("htmx:sendError", function () {
    toast("Network error: could not reach the panel.");
  });
})();
