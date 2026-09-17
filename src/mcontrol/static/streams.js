(function () {
  "use strict";
  const output = document.querySelector("#console-output");
  if (!output) return;
  const form = document.querySelector("[data-console-form]"), input = form.querySelector('[name="command"]');
  const send = form.querySelector('[type="submit"]'), error = document.querySelector("[data-command-error]");
  const rconStatus = document.querySelector("[data-stream-status-label]"), logStatus = document.querySelector("[data-log-status]");
  const jump = document.querySelector("[data-stream-jump]");
  const search = document.querySelector("[data-console-search]");
  const reconnectButton = document.querySelector("[data-stream-retry]");
  let logTimer, logFailed = false;
  let pinned = true, pending = 0, rcon = null, logs = null, ready = false, logEnded = false;
  let retry = 0, readyTimer, retryTimer, histIndex = -1, draft = "", acceptedCommand = "", logCursor = "";
  const historyKey = "console-history:" + form.dataset.consoleForm;
  let state = document.querySelector("#lifecycle-buttons")?.dataset.state;
  function running() { return ["running", "starting", "restarting"].includes(state); }
  function setReady(value, label) {
    ready = value; send.disabled = !value; rconStatus.textContent = label;
    const status = rconStatus.closest("[data-stream-status]");
    status.dataset.state = value ? "live" : "closed";
    status.hidden = value;
    reconnectButton.hidden = !logFailed && (value || !running());
  }
  function matches(line) {
    return line.textContent.toLowerCase().includes(search.value.toLowerCase());
  }
  function filter() { Array.from(output.children).forEach(line => { line.hidden = !matches(line); }); }
  function bottom() { pinned = true; output.scrollTop = output.scrollHeight; pending = 0; jump.hidden = true; }
  function append(html) {
    const template = document.createElement("template"); template.innerHTML = html;
    // Endpoints escape log text and return classified spans. Keep only those
    // spans so filtering does not leave blank newline text nodes behind.
    Array.from(template.content.children).forEach(line => {
      if (line.tagName !== "SPAN") return;
      line.hidden = !matches(line); output.append(line);
      if (!line.hidden) pending += 1;
    });
    if (pinned) {
      while (output.children.length > 4000) output.firstElementChild.remove();
      bottom();
    } else {
      jump.querySelector("[data-stream-jump-count]").textContent = pending;
      jump.hidden = pending === 0;
    }
  }
  output.addEventListener("scroll", () => { pinned = output.scrollHeight - output.scrollTop - output.clientHeight < 40; if (pinned) { pending = 0; jump.hidden = true; } });
  jump.addEventListener("click", bottom);
  search.addEventListener("input", filter);
  const searchToggle = document.querySelector("[data-console-search-toggle]");
  const searchTools = document.querySelector("#console-search-tools");
  function toggleSearch(open) {
    if (open) {
      const panel = output.closest(".panel");
      if (panel.dataset.collapsed === "true") panel.querySelector(".panel__collapse").click();
    } else {
      search.value = "";
      filter();
    }
    searchTools.hidden = !open;
    searchToggle.setAttribute("aria-expanded", String(open));
    (open ? search : searchToggle).focus();
  }
  searchToggle.addEventListener("click", () => toggleSearch(searchTools.hidden));
  search.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      toggleSearch(false);
    }
  });
  function closeRcon() {
    clearTimeout(readyTimer); clearTimeout(retryTimer); rcon?.close(); rcon = null;
    setReady(false, running() ? "Commands paused" : "Commands offline");
  }
  function connectRcon() {
    if (document.hidden || !running() || rcon) return;
    setReady(false, "Commands connecting…");
    const source = new EventSource(output.dataset.rconSrc); rcon = source;
    function reconnect() {
      if (rcon !== source) return;
      closeRcon(); setReady(false, "Commands reconnecting…");
      error.textContent = "Command connection unavailable. Retrying…";
      retryTimer = setTimeout(connectRcon, Math.min(15000, 1000 * 2 ** retry++));
    }
    readyTimer = setTimeout(reconnect, 12000);
    source.onmessage = event => append(event.data);
    source.addEventListener("ready", () => {
      if (rcon !== source) return;
      clearTimeout(readyTimer); retry = 0; setReady(true, "Commands ready"); error.textContent = "";
    });
    source.addEventListener("closed", () => {
      if (rcon !== source) return;
      closeRcon(); setReady(false, "Commands unavailable");
      error.textContent = "Command connection ended. Check the console output and RCON settings.";
    });
    source.onerror = reconnect;
  }
  function setLogStatus(label, healthy = false) {
    logStatus.textContent = label;
    logStatus.hidden = healthy;
  }
  function connectLogs() {
    if (document.hidden || logs || logEnded) return;
    const url = new URL(output.dataset.logSrc, location.href);
    if (logCursor) url.searchParams.set("resume", "1");
    logs = new EventSource(url);
    logTimer = setTimeout(() => { logFailed = true; setLogStatus("Logs unavailable after 12 seconds"); reconnectButton.hidden = false; }, 12000);
    logs.onopen = () => { clearTimeout(logTimer); logFailed = false; reconnectButton.hidden = ready || !running(); setLogStatus(running() ? "Logs live" : "Saved logs", true); };
    logs.onmessage = event => { logCursor = event.lastEventId || logCursor; append(event.data); };
    logs.onerror = () => { logFailed = true; reconnectButton.hidden = false; setLogStatus("Logs reconnecting…"); };
    logs.addEventListener("closed", () => { clearTimeout(logTimer); logs?.close(); logs = null; logEnded = true; logFailed = true; reconnectButton.hidden = false; setLogStatus("Log stream ended"); });
  }
  reconnectButton.addEventListener("click", () => {
    clearTimeout(logTimer); closeRcon(); logs?.close(); logs = null; logEnded = false; retry = 0;
    connectLogs(); connectRcon();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { clearTimeout(logTimer); closeRcon(); logs?.close(); logs = null; setLogStatus(logEnded ? "Log stream ended" : "Logs paused"); }
    else { connectLogs(); connectRcon(); }
  });
  document.body.addEventListener("mc:state-changed", event => {
    const next = event.detail.state, changed = next !== state; state = next;
    if (!running()) closeRcon();
    else if (changed) { logEnded = false; connectLogs(); connectRcon(); }
  });
  function history() { try { const h = JSON.parse(sessionStorage.getItem(historyKey)); return Array.isArray(h) ? h : []; } catch (_) { return []; } }
  form.addEventListener("htmx:beforeRequest", event => {
    if (!ready) { event.preventDefault(); error.textContent = "Wait for the command connection before sending."; return; }
    acceptedCommand = input.value; error.textContent = "";
  });
  form.addEventListener("htmx:afterRequest", event => {
    send.disabled = !ready;
    if (event.detail.xhr?.status === 204) {
      const h = history(); if (h[h.length - 1] !== acceptedCommand) h.push(acceptedCommand);
      try { sessionStorage.setItem(historyKey, JSON.stringify(h.slice(-100))); } catch (_) {}
      if (input.value === acceptedCommand) input.value = "";
      histIndex = -1; input.focus();
    } else {
      let message = "Command failed. Your text has been kept.";
      try { message = JSON.parse(event.detail.xhr.responseText).detail || message; } catch (_) {}
      error.textContent = message;
    }
  });
  input.addEventListener("keydown", event => {
    if (!["ArrowUp", "ArrowDown"].includes(event.key)) return;
    const h = history(); if (!h.length) return;
    if (event.key === "ArrowUp") { if (histIndex === -1) { draft = input.value; histIndex = h.length - 1; } else histIndex = Math.max(0, histIndex - 1); input.value = h[histIndex]; }
    else if (histIndex !== -1) { histIndex += 1; if (histIndex >= h.length) { histIndex = -1; input.value = draft; } else input.value = h[histIndex]; }
    event.preventDefault();
  });
  window.addEventListener("pagehide", () => { closeRcon(); logs?.close(); logs = null; });
  connectLogs(); connectRcon();
})();
