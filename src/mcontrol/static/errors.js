(function () {
  "use strict";
  const busy = new WeakSet();
  const notices = new Map();
  let sequence = 0;
  function targetOf(d) { return d.target || d.elt; }
  function keyOf(target) { return target.id || (target.dataset.requestKey ||= "request-" + ++sequence); }
  function clear(target) {
    if (!target) return;
    const key = keyOf(target); notices.get(key)?.remove(); notices.delete(key);
    target.removeAttribute("data-stale");
    if (target.id === "server-resources") {
      const pill = document.querySelector("#state-pill");
      if (pill?.dataset.previousLabel) { pill.textContent = pill.dataset.previousLabel; delete pill.dataset.previousLabel; pill.classList.remove("state-pill--unreachable"); }
      document.querySelectorAll("[data-stale-disabled]").forEach(button => { button.disabled = button.dataset.staleDisabled === "true"; delete button.dataset.staleDisabled; });
    }
  }
  function failure(evt, fallback) {
    const d = evt.detail || {}, target = targetOf(d);
    if (!target || !target.isConnected) return;
    const request = d.requestConfig || {}, verb = (request.verb || "get").toLowerCase();
    let message = fallback;
    try { const detail = JSON.parse(d.xhr.responseText).detail; if (typeof detail === "string") message = detail; } catch (_) {}
    if (d.elt?.matches("[data-console-form]")) return;
    clear(target);
    target.dataset.stale = "true";
    if (target.id === "server-resources") {
      const pill = document.querySelector("#state-pill");
      if (pill) { pill.dataset.previousLabel = pill.textContent; pill.textContent = "Unavailable"; pill.classList.add("state-pill--unreachable"); }
      document.querySelectorAll("[data-lifecycle-button]").forEach(button => { button.dataset.staleDisabled = String(button.disabled); button.disabled = true; });
    }
    target.querySelectorAll(".skeleton").forEach(el => el.remove());
    target.querySelectorAll("[data-tree-status]").forEach(el => el.remove());
    if (target.matches(".hx-slot, .resources-strip--loading, [data-loading]")) target.replaceChildren();
    if (target.id === "fleet") {
      target.querySelectorAll(".state-pill").forEach(pill => { pill.textContent = "Unavailable"; pill.className = "state-pill state-pill--unreachable"; });
      target.querySelectorAll(".server-card__actions button").forEach(button => { button.disabled = true; });
    }
    const notice = document.createElement("div"); notice.className = "request-notice"; notice.setAttribute("role", "status");
    const text = document.createElement("span");
    const label = d.elt?.dataset.asyncLabel
      || target.closest('.panel')?.querySelector('.panel__title')?.textContent
      || ({'server-resources': 'Server status', 'server-disk': 'Disk usage', 'fleet': 'Servers', 'online-chip': 'Players'})[target.id];
    text.textContent = (label ? label + ": " : "") + message;
    notice.append(text);
    if (verb === "get") {
      const retry = document.createElement("button"); retry.className = "btn btn--sm"; retry.type = "button"; retry.textContent = "Retry";
      retry.addEventListener("click", () => {
        const url = d.pathInfo?.requestPath || request.path || d.elt?.getAttribute("hx-get");
        if (!url) return;
        retry.disabled = true;
        window.htmx.ajax("GET", url, { source: d.elt?.isConnected ? d.elt : target, target, swap: d.elt?.getAttribute("hx-swap") || "innerHTML" }).finally(() => { retry.disabled = false; });
      }); notice.append(retry);
    }
    if (d.elt?.matches("[data-membership-change]")) {
      const checkbox = d.elt.querySelector('input[type="checkbox"]');
      if (checkbox) checkbox.checked = d.elt.querySelector('input[name="enabled"]').value !== "1";
      const status = document.querySelector("[data-membership-status]");
      if (status) status.textContent = "Change failed. Previous access kept.";
    }
    const dismiss = document.createElement("button");
    dismiss.className = "flash-msg__dismiss"; dismiss.type = "button";
    dismiss.setAttribute("aria-label", "Dismiss notification"); dismiss.textContent = "\u00d7";
    dismiss.addEventListener("click", () => { notice.remove(); notices.delete(keyOf(target)); });
    notice.append(dismiss);
    // Keep persistent failures and Retry outside the workspace grid and swap targets.
    document.getElementById("flash-stack").append(notice);
    notices.set(keyOf(target), notice);
  }
  document.addEventListener("htmx:configRequest", evt => {
    if (evt.detail.verb.toLowerCase() === "get") evt.detail.timeout = 12000;
  });
  document.addEventListener("htmx:beforeRequest", evt => {
    const d = evt.detail, target = targetOf(d), polling = d.elt?.hasAttribute("data-poll");
    if (polling && (document.hidden || busy.has(target) || document.querySelector('[data-lifecycle-button][aria-busy="true"]') || document.activeElement?.closest("#fleet"))) { evt.preventDefault(); return; }
    busy.add(target); target.setAttribute("aria-busy", "true");
    if (d.elt?.matches("[data-membership-change]")) {
      const status = document.querySelector("[data-membership-status]");
      if (status) status.textContent = "Updating server access…";
    }
  });
  document.addEventListener("htmx:beforeSwap", evt => {
    const d = evt.detail, xhr = d.xhr; if (!xhr) return;
    const type = xhr.getResponseHeader("Content-Type") || "";
    if ((xhr.status === 409 || xhr.status === 422) && type.includes("text/html")) { d.shouldSwap = true; d.isError = false; }
    if (xhr.status >= 200 && xhr.status < 300) clear(d.target);
  });
  document.addEventListener("htmx:afterRequest", evt => {
    const d = evt.detail, target = targetOf(d);
    if (target) { busy.delete(target); target.removeAttribute("aria-busy"); }
  });
  document.addEventListener("htmx:responseError", e => failure(e, `Could not load this information (HTTP ${e.detail.xhr?.status}). Previous values may be stale.`));
  document.addEventListener("htmx:sendError", e => failure(e, "Connection lost. Previous values may be stale."));
  document.addEventListener("htmx:timeout", e => failure(e, "No response after 12 seconds. Previous values may be stale."));
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) document.querySelectorAll("[data-poll]").forEach(el => window.htmx?.trigger(el, "mc:refresh"));
  });
})();
