(function () {
  "use strict";
  let rosterQ = "", rosterServer = "", memberQ = "";
  function rosterFilter() {
    const select = document.querySelector("[data-roster-server]"), rows = Array.from(document.querySelectorAll("[data-roster-name]"));
    if (select) {
      const names = [...new Set(rows.flatMap(row => Array.from(row.querySelectorAll('a[href^="/servers/"]')).map(a => a.textContent.trim())))].sort();
      names.forEach(name => { if (!Array.from(select.options).some(o => o.value === name)) select.add(new Option(name, name)); });
      select.value = rosterServer;
      document.querySelector("[data-roster-search]").value = rosterQ;
    }
    let count = 0;
    rows.forEach(row => {
      const names = Array.from(row.querySelectorAll('a[href^="/servers/"]')).map(a => a.textContent.trim());
      row.hidden = !row.dataset.rosterName.toLowerCase().includes(rosterQ.toLowerCase()) || (!!rosterServer && !names.includes(rosterServer));
      if (!row.hidden) count++;
    });
    const empty = document.querySelector("[data-roster-empty]"); if (empty) empty.hidden = count > 0 || (!rosterQ && !rosterServer);
    const input = document.querySelector("[data-members-search]"); if (input) input.value = memberQ;
    let members = 0;
    document.querySelectorAll("[data-member-name]").forEach(row => { row.hidden = !row.dataset.memberName.toLowerCase().includes(memberQ.toLowerCase()); if (!row.hidden) members++; });
    const noMembers = document.querySelector("[data-members-empty]"); if (noMembers) noMembers.hidden = members > 0 || !memberQ;
  }
  document.addEventListener("input", e => {
    if (e.target.matches("[data-roster-search]")) { rosterQ = e.target.value; rosterFilter(); }
    if (e.target.matches("[data-roster-server]")) { rosterServer = e.target.value; rosterFilter(); }
    if (e.target.matches("[data-members-search]")) { memberQ = e.target.value; rosterFilter(); }
  });
  const files = document.querySelector(".files-pane");
  function openFile() {
    if (!files || !files.querySelector(".file-view__head")) return;
    files.dataset.fileOpen = "true"; files.querySelector("[data-files-back]").hidden = false;
  }
  files?.querySelector("[data-files-back]").addEventListener("click", () => {
    files.dataset.fileOpen = "false"; files.querySelector("[data-files-back]").hidden = true;
    files.querySelector("#file-search-input").focus();
  });
  const divider = files?.querySelector(".file-divider");
  function size(width) { width = Math.max(160, Math.min(360, width)); files.style.setProperty("--file-nav-width", width + "px"); divider.setAttribute("aria-valuenow", String(width)); }
  files?.querySelector("[data-file-nav-size]").addEventListener("change", e => size(Number(e.target.value)));
  divider?.addEventListener("pointerdown", e => {
    divider.setPointerCapture(e.pointerId); const start = e.clientX, width = Number(divider.getAttribute("aria-valuenow"));
    const move = ev => size(width + ev.clientX - start);
    divider.addEventListener("pointermove", move);
    divider.addEventListener("pointerup", () => divider.removeEventListener("pointermove", move), { once: true });
  });
  divider?.addEventListener("keydown", e => { if (["ArrowLeft", "ArrowRight"].includes(e.key)) { e.preventDefault(); size(Number(divider.getAttribute("aria-valuenow")) + (e.key === "ArrowRight" ? 20 : -20)); } });
  document.addEventListener("htmx:afterSettle", e => {
    rosterFilter();
    if (e.detail.target?.id === "file-view" || e.target.id === "file-view") openFile();
  });
  function freshness() {
    document.querySelectorAll("[data-observed-at]").forEach(time => {
      const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(time.dataset.observedAt)) / 1000));
      if (!Number.isFinite(seconds)) return;
      time.textContent = seconds < 5 ? "just now" : seconds < 60 ? seconds + "s ago" : Math.floor(seconds / 60) + "m ago";
      time.title = new Date(time.dataset.observedAt).toLocaleString();
    });
  }
  setInterval(() => { if (!document.hidden) freshness(); }, 1000);
  rosterFilter(); openFile();
})();
