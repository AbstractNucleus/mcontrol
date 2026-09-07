(function () {
  "use strict";
  const menu = document.querySelector("[data-mobile-menu]"), sidebar = document.querySelector("#primary-sidebar"), backdrop = document.querySelector("[data-close-nav]");
  function nav(open) {
    document.documentElement.dataset.mobileNav = String(open); backdrop.hidden = !open;
    menu.setAttribute("aria-expanded", String(open));
    document.querySelector("#main").inert = open;
    if (open) sidebar.querySelector("a").focus(); else menu.focus();
  }
  menu?.addEventListener("click", () => nav(menu.getAttribute("aria-expanded") !== "true"));
  backdrop?.addEventListener("click", () => nav(false));
  document.addEventListener("keydown", e => {
    if (document.documentElement.dataset.mobileNav !== "true") return;
    if (e.key === "Escape") { nav(false); e.preventDefault(); }
    if (e.key === "Tab") {
      const items = [menu, ...Array.from(sidebar.querySelectorAll('a, button, input')).filter(el => !el.disabled && el.getClientRects().length)];
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  matchMedia("(min-width: 768px)").addEventListener("change", e => { if (e.matches && document.documentElement.dataset.mobileNav === "true") nav(false); });
  function fleetFilter() {
    const state = document.querySelector("[data-fleet-state]")?.value || "";
    let visible = 0;
    document.querySelectorAll("#fleet .server-card").forEach(row => {
      row.hidden = !!state && row.querySelector(".state-pill").textContent.trim() !== state;
      if (!row.hidden) visible++;
      const link = Array.from(document.querySelectorAll(".sidebar__server")).find(a => a.getAttribute("href") === "/servers/" + row.dataset.name);
      if (link) { link.title = row.dataset.name + " (" + row.querySelector(".state-pill").textContent.trim() + ")"; link.querySelector(".sidebar__server-dot").className = "sidebar__server-dot sidebar__server-dot--" + row.dataset.state; }
    });
    const empty = document.querySelector("[data-fleet-empty]"); if (empty) empty.hidden = visible > 0 || !state;
    document.querySelectorAll("[data-fleet-filter]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.fleetFilter === state)));
  }
  document.addEventListener("click", e => {
    const chip = e.target.closest("[data-fleet-filter]"), clear = e.target.closest("[data-fleet-clear]");
    if (!chip && !clear) return;
    const select = document.querySelector("[data-fleet-state]");
    if (!select) return;
    select.value = chip ? chip.dataset.fleetFilter : "";
    fleetFilter();
  });
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
    if (e.target.matches("[data-fleet-state]")) fleetFilter();
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
    fleetFilter(); rosterFilter();
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
  fleetFilter(); rosterFilter(); openFile();
})();
