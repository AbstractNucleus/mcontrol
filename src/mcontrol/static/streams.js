// Live-stream pane behavior (log + RCON console on the detail page).
//
// Three responsibilities, all keyed off opt-in data attributes so the
// module is a no-op on pages without stream panes:
//
//   1. Stick-to-bottom scroll pinning on [data-stream-scroll] panes.
//      Pinned state is tracked in the scroll listener (a MutationObserver
//      fires after the append, when scrollHeight has already grown, so
//      "was I at the bottom?" cannot be computed there). While pinned,
//      retained content is capped so day-long tails don't grow unbounded;
//      trimming only happens while pinned so a user reading history never
//      has content shift under them.
//   2. A floating "N new lines" chip when output lands below the fold.
//   3. Console form niceties: reset + refocus after an accepted command,
//      ArrowUp/Down command history (sessionStorage, per server), and
//      connection-state dots driven by the htmx SSE extension's events.
(function () {
  "use strict";

  var MAX_NODES = 4000;

  function initPane(pane) {
    var body = pane.parentElement;
    var jump = body ? body.querySelector("[data-stream-jump]") : null;
    var jumpCount = jump ? jump.querySelector("[data-stream-jump-count]") : null;
    var pinned = true;
    var pending = 0;

    function jumpToBottom() {
      pane.scrollTop = pane.scrollHeight;
      pending = 0;
      if (jump) jump.hidden = true;
    }

    pane.addEventListener("scroll", function () {
      pinned = pane.scrollHeight - pane.scrollTop - pane.clientHeight <= 40;
      if (pinned && jump && !jump.hidden) {
        pending = 0;
        jump.hidden = true;
      }
    });

    new MutationObserver(function () {
      if (pinned) {
        pane.scrollTop = pane.scrollHeight;
        while (pane.childNodes.length > MAX_NODES) {
          pane.removeChild(pane.firstChild);
        }
      } else if (jump) {
        pending += 1;
        if (jumpCount) jumpCount.textContent = String(pending);
        jump.hidden = false;
      }
    }).observe(pane, { childList: true });

    if (jump) jump.addEventListener("click", jumpToBottom);
  }

  document.querySelectorAll("[data-stream-scroll]").forEach(initPane);

  // ---- Connection-state dots ------------------------------------------
  function setStatus(el, state, label) {
    var section = el.closest ? el.closest("section") : null;
    var status = section ? section.querySelector("[data-stream-status]") : null;
    if (!status) return;
    status.setAttribute("data-state", state);
    var text = status.querySelector("[data-stream-status-label]");
    if (text) text.textContent = label;
  }

  document.body.addEventListener("htmx:sseOpen", function (evt) {
    setStatus(evt.target, "live", "live");
  });
  document.body.addEventListener("htmx:sseError", function (evt) {
    setStatus(evt.target, "reconnecting", "reconnecting…");
  });
  document.body.addEventListener("htmx:sseClose", function (evt) {
    setStatus(evt.target, "closed", "stream ended");
  });

  // ---- Console form: reset on accept + command history ----------------
  var form = document.querySelector("[data-console-form]");
  if (!form) return;
  var input = form.querySelector('input[name="command"]');
  var histKey = "console-history:" + (form.getAttribute("data-console-form") || "");
  var histIndex = -1; // -1 = live (unsubmitted) entry
  var draft = "";

  function history() {
    try {
      return JSON.parse(sessionStorage.getItem(histKey)) || [];
    } catch (_) {
      return [];
    }
  }

  function pushHistory(cmd) {
    var h = history();
    if (h[h.length - 1] !== cmd) h.push(cmd);
    while (h.length > 100) h.shift();
    try { sessionStorage.setItem(histKey, JSON.stringify(h)); } catch (_) {}
  }

  form.addEventListener("htmx:afterRequest", function (evt) {
    if (evt.detail.elt !== form) return;
    if (evt.detail.xhr && evt.detail.xhr.status === 204) {
      if (input && input.value) pushHistory(input.value);
      form.reset();
      histIndex = -1;
      if (input) input.focus();
    }
  });

  if (!input) return;
  input.addEventListener("keydown", function (evt) {
    if (evt.key !== "ArrowUp" && evt.key !== "ArrowDown") return;
    var h = history();
    if (!h.length) return;
    if (evt.key === "ArrowUp") {
      if (histIndex === -1) {
        draft = input.value;
        histIndex = h.length - 1;
      } else if (histIndex > 0) {
        histIndex -= 1;
      }
      input.value = h[histIndex];
    } else {
      if (histIndex === -1) return;
      histIndex += 1;
      if (histIndex >= h.length) {
        histIndex = -1;
        input.value = draft;
      } else {
        input.value = h[histIndex];
      }
    }
    evt.preventDefault();
  });
})();
