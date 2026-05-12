// Drag-drop + button-fallback uploads for the file tree (slice 5 PR 3).
//
// Decision 016 (no bundler) means this is plain ES2020. It's deliberately
// independent of htmx for the upload round-trip: we hold the FileList in
// memory between the first POST and the operator's confirmed force=true
// retry, which an htmx form-submit can't do (the browser doesn't keep
// File handles across responses).
//
// Drop targets: any element with `data-upload-target` and `data-upload-path`.
// Triggers (button fallback): any element with `data-upload-trigger` and
// `data-upload-path`; clicking opens the shared hidden file input.

const STATE = { highlighted: null };

function tree() { return document.getElementById("file-tree"); }
function status() { return document.getElementById("file-action-status"); }
function fileInput() { return document.getElementById("file-upload-input"); }
function pane(el) { return el ? el.closest(".files-pane") : null; }
function serverName() {
  const p = document.querySelector(".files-pane");
  return p ? p.dataset.serverName : null;
}

function cssEscape(s) {
  return (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/(["\\])/g, "\\$1");
}

function highlight(target) {
  if (STATE.highlighted && STATE.highlighted !== target) {
    STATE.highlighted.classList.remove("is-drop-active");
  }
  if (target) target.classList.add("is-drop-active");
  STATE.highlighted = target;
}

function unhighlight() {
  if (STATE.highlighted) {
    STATE.highlighted.classList.remove("is-drop-active");
    STATE.highlighted = null;
  }
}

function isFilesDrag(evt) {
  return evt.dataTransfer && Array.from(evt.dataTransfer.types || []).includes("Files");
}

document.addEventListener("dragenter", (evt) => {
  if (!isFilesDrag(evt)) return;
  const target = evt.target.closest && evt.target.closest("[data-upload-target]");
  if (!target) return;
  evt.preventDefault();
  highlight(target);
});

document.addEventListener("dragover", (evt) => {
  if (!isFilesDrag(evt)) return;
  const target = evt.target.closest && evt.target.closest("[data-upload-target]");
  if (!target) return;
  evt.preventDefault();
  evt.dataTransfer.dropEffect = "copy";
  highlight(target);
});

document.addEventListener("dragleave", (evt) => {
  const related = evt.relatedTarget;
  // Inside-target moves still fire dragleave; only unhighlight when we
  // genuinely left every drop target.
  if (related && related.closest && related.closest("[data-upload-target]")) return;
  unhighlight();
});

document.addEventListener("drop", async (evt) => {
  const target = evt.target.closest && evt.target.closest("[data-upload-target]");
  if (!target) return;
  evt.preventDefault();
  unhighlight();
  const path = target.dataset.uploadPath || "";
  const files = Array.from(evt.dataTransfer.files || []);
  if (files.length === 0) return;
  await uploadFiles(path, files, false);
});

document.addEventListener("click", (evt) => {
  const trigger = evt.target.closest && evt.target.closest("[data-upload-trigger]");
  if (!trigger) return;
  evt.preventDefault();
  const input = fileInput();
  if (!input) return;
  input.dataset.targetPath = trigger.dataset.uploadPath || "";
  input.value = ""; // ensure `change` fires even when re-picking the same file
  input.click();
});

// Slice 5 follow-up: close the per-entry ⋯ popover after any action click
// inside it, so the next action doesn't have to first dismiss the menu.
// Also close any open popover on a click outside it — <details> doesn't
// do outside-click dismissal natively.
// requestAnimationFrame defers to the next frame so the action's own
// handler runs first (e.g. opening the rename form, navigating download).
document.addEventListener("click", (evt) => {
  const target = evt.target;
  const inMenu = target.closest && target.closest(".file-tree__menu-panel");
  if (inMenu) {
    const det = inMenu.closest("details.file-tree__menu");
    if (det) requestAnimationFrame(() => { det.open = false; });
    return;
  }
  // Outside-click dismissal: close every open menu unless the click
  // landed on a menu's own summary (which toggles natively).
  const onSummary = target.closest && target.closest(".file-tree__menu-trigger");
  document.querySelectorAll("details.file-tree__menu[open]").forEach((det) => {
    if (onSummary && det.contains(onSummary)) return;
    det.open = false;
  });
});

document.addEventListener("change", async (evt) => {
  if (!evt.target || evt.target.id !== "file-upload-input") return;
  const path = evt.target.dataset.targetPath || "";
  const files = Array.from(evt.target.files || []);
  if (files.length === 0) return;
  await uploadFiles(path, files, false);
});

async function uploadFiles(path, files, force) {
  const name = serverName();
  if (!name) return;

  const fd = new FormData();
  fd.append("path", path);
  if (force) fd.append("force", "true");
  for (const f of files) fd.append("files", f, f.name);

  let resp;
  try {
    resp = await fetch(`/servers/${encodeURIComponent(name)}/files/upload`, {
      method: "POST",
      body: fd,
    });
  } catch (err) {
    showError(`upload failed: ${err.message}`);
    return;
  }

  if (resp.status === 409) {
    showConflict(await resp.text(), () => uploadFiles(path, files, true));
    return;
  }
  if (!resp.ok) {
    showError(await errorMessageFor("upload", resp));
    return;
  }

  swapTreeAt(path, await resp.text());
  const s = status();
  if (s) s.innerHTML = "";
  // Re-arm htmx for the freshly-injected tree subtree (lazy hx-get on
  // any newly-listed subfolders, click-to-view on files).
  const t = tree();
  if (t && window.htmx && window.htmx.process) window.htmx.process(t);
}

function swapTreeAt(path, html) {
  if (path === "") {
    const t = tree();
    if (t) t.innerHTML = html;
    return;
  }
  const sel = `[data-upload-target][data-upload-path="${cssEscape(path)}"] > .file-tree__children`;
  const ul = document.querySelector(sel);
  if (ul) ul.innerHTML = html;
}

function showConflict(html, onOverwrite) {
  const s = status();
  if (!s) return;
  s.innerHTML = html;
  s.querySelectorAll("[data-upload-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.uploadAction;
      s.innerHTML = "";
      if (action === "overwrite") onOverwrite();
    });
  });
}

function showError(msg) {
  const s = status();
  if (!s) return;
  s.innerHTML = `<div class="file-upload-error t-caption">${escapeHtml(msg)}</div>`;
}

// Surface the backend's `detail` field (FastAPI's HTTPException shape)
// when available; fall back to the status code if the body isn't JSON
// or has no detail. Used by every non-OK action response except the
// upload-conflict 409 which returns an HTML partial.
async function errorMessageFor(verb, resp) {
  try {
    const data = await resp.clone().json();
    if (data && typeof data.detail === "string" && data.detail) {
      return `${verb} failed: ${data.detail}`;
    }
  } catch (_err) { /* not JSON — fall through */ }
  return `${verb} failed: HTTP ${resp.status}`;
}

// ---- delete + mkdir (slice 5 PR 4) -----------------------------------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

function parentOf(p) {
  if (!p) return "";
  const i = p.lastIndexOf("/");
  return i < 0 ? "" : p.slice(0, i);
}

document.addEventListener("click", (evt) => {
  const del = evt.target.closest && evt.target.closest("[data-action-delete]");
  if (del) {
    evt.preventDefault();
    showDeleteConfirm(del.dataset);
    return;
  }
  const mk = evt.target.closest && evt.target.closest("[data-action-mkdir]");
  if (mk) {
    evt.preventDefault();
    showMkdirForm(mk.dataset.actionPath || "");
    return;
  }
  const ren = evt.target.closest && evt.target.closest("[data-action-rename]");
  if (ren) {
    evt.preventDefault();
    showRenameForm(ren.dataset.actionPath || "", ren.dataset.actionName || "");
    return;
  }
  const mv = evt.target.closest && evt.target.closest("[data-action-move]");
  if (mv) {
    evt.preventDefault();
    showMoveModal(mv.dataset.actionPath || "", mv.dataset.actionName || "");
  }
});

function showDeleteConfirm(ds) {
  const s = status();
  if (!s) return;
  const path = ds.actionPath || "";
  const dispName = ds.actionName || path;
  const kind = ds.actionKind || "file";
  const isDir = kind === "dir";
  const safeName = escapeHtml(dispName);
  s.innerHTML = isDir
    ? `<div class="file-delete-confirm file-delete-confirm--danger" id="file-delete-confirm">
         <p class="t-caption">Delete folder <code>${safeName}/</code> and everything inside?</p>
         <p class="t-caption">Type <code>${safeName}</code> to confirm:</p>
         <div class="file-delete-confirm__actions">
           <input type="text" autocomplete="off" data-confirm-input>
           <button type="button" class="file-delete-confirm__btn file-delete-confirm__btn--danger" data-confirm-submit disabled>Delete</button>
           <button type="button" class="file-delete-confirm__btn" data-confirm-cancel>Cancel</button>
         </div>
       </div>`
    : `<div class="file-delete-confirm" id="file-delete-confirm">
         <p class="t-caption">Delete <code>${safeName}</code>?</p>
         <div class="file-delete-confirm__actions">
           <button type="button" class="file-delete-confirm__btn file-delete-confirm__btn--danger" data-confirm-submit>Delete</button>
           <button type="button" class="file-delete-confirm__btn" data-confirm-cancel>Cancel</button>
         </div>
       </div>`;

  const submit = s.querySelector("[data-confirm-submit]");
  const cancel = s.querySelector("[data-confirm-cancel]");
  const input = s.querySelector("[data-confirm-input]");

  if (isDir && input && submit) {
    input.addEventListener("input", () => {
      submit.disabled = input.value !== dispName;
    });
    input.focus();
  }

  submit.addEventListener("click", async () => {
    if (submit.disabled) return;
    await performDelete(path, isDir ? dispName : "");
  });
  cancel.addEventListener("click", () => { s.innerHTML = ""; });
}

function showMkdirForm(parentPath) {
  const s = status();
  if (!s) return;
  const label = parentPath === "" ? "root" : parentPath + "/";
  s.innerHTML = `<div class="file-action-form" id="file-mkdir-form">
       <p class="t-caption">New folder in <code>${escapeHtml(label)}</code>:</p>
       <div class="file-action-form__actions">
         <input type="text" autocomplete="off" placeholder="folder name" data-mkdir-input>
         <button type="button" class="file-action-form__btn" data-mkdir-submit>Create</button>
         <button type="button" class="file-action-form__btn" data-mkdir-cancel>Cancel</button>
       </div>
     </div>`;

  const input = s.querySelector("[data-mkdir-input]");
  const submit = s.querySelector("[data-mkdir-submit]");
  const cancel = s.querySelector("[data-mkdir-cancel]");

  if (input) input.focus();
  input.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") { evt.preventDefault(); submit.click(); }
    if (evt.key === "Escape") { evt.preventDefault(); cancel.click(); }
  });
  submit.addEventListener("click", async () => {
    const name = (input.value || "").trim();
    if (!name) return;
    await performMkdir(parentPath, name);
  });
  cancel.addEventListener("click", () => { s.innerHTML = ""; });
}

async function performDelete(path, confirmName) {
  const name = serverName();
  if (!name) return;
  const fd = new FormData();
  fd.append("path", path);
  if (confirmName) fd.append("confirm_name", confirmName);

  let resp;
  try {
    resp = await fetch(`/servers/${encodeURIComponent(name)}/files/delete`, {
      method: "POST",
      body: fd,
    });
  } catch (err) {
    showError(`delete failed: ${err.message}`);
    return;
  }

  if (!resp.ok) {
    showError(await errorMessageFor("delete", resp));
    return;
  }

  const html = await resp.text();
  swapTreeAt(parentOf(path), html);
  const s = status();
  if (s) s.innerHTML = "";
  const t = tree();
  if (t && window.htmx && window.htmx.process) window.htmx.process(t);
}

async function performMkdir(parentPath, dirname) {
  const name = serverName();
  if (!name) return;
  const fd = new FormData();
  fd.append("path", parentPath);
  fd.append("dirname", dirname);

  let resp;
  try {
    resp = await fetch(`/servers/${encodeURIComponent(name)}/files/mkdir`, {
      method: "POST",
      body: fd,
    });
  } catch (err) {
    showError(`mkdir failed: ${err.message}`);
    return;
  }

  if (!resp.ok) {
    showError(await errorMessageFor("mkdir", resp));
    return;
  }

  const html = await resp.text();
  swapTreeAt(parentPath, html);
  const s = status();
  if (s) s.innerHTML = "";
  const t = tree();
  if (t && window.htmx && window.htmx.process) window.htmx.process(t);
}

// ---- rename + move (slice 5 PR 5) ------------------------------------

function showRenameForm(path, currentName) {
  const s = status();
  if (!s) return;
  s.innerHTML = `<div class="file-action-form" id="file-rename-form">
       <p class="t-caption">Rename <code>${escapeHtml(currentName)}</code> to:</p>
       <div class="file-action-form__actions">
         <input type="text" autocomplete="off" data-rename-input>
         <button type="button" class="file-action-form__btn" data-rename-submit>Rename</button>
         <button type="button" class="file-action-form__btn" data-rename-cancel>Cancel</button>
       </div>
     </div>`;

  const input = s.querySelector("[data-rename-input]");
  const submit = s.querySelector("[data-rename-submit]");
  const cancel = s.querySelector("[data-rename-cancel]");

  input.value = currentName;
  input.focus();
  // Select the basename without the extension to make the common-case
  // edit (filename-without-extension) one keystroke instead of two.
  const dot = currentName.lastIndexOf(".");
  if (dot > 0) input.setSelectionRange(0, dot);
  else input.select();

  input.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") { evt.preventDefault(); submit.click(); }
    if (evt.key === "Escape") { evt.preventDefault(); cancel.click(); }
  });
  submit.addEventListener("click", async () => {
    const newName = (input.value || "").trim();
    if (!newName || newName === currentName) { s.innerHTML = ""; return; }
    await performRename(path, newName);
  });
  cancel.addEventListener("click", () => { s.innerHTML = ""; });
}

async function performRename(path, newName) {
  const name = serverName();
  if (!name) return;
  const fd = new FormData();
  fd.append("path", path);
  fd.append("new_name", newName);

  let resp;
  try {
    resp = await fetch(`/servers/${encodeURIComponent(name)}/files/rename`, {
      method: "POST",
      body: fd,
    });
  } catch (err) {
    showError(`rename failed: ${err.message}`);
    return;
  }

  if (!resp.ok) {
    showError(await errorMessageFor("rename", resp));
    return;
  }

  const html = await resp.text();
  swapTreeAt(parentOf(path), html);
  const s = status();
  if (s) s.innerHTML = "";
  const t = tree();
  if (t && window.htmx && window.htmx.process) window.htmx.process(t);
}

function showMoveModal(sourcePath, sourceName) {
  const s = status();
  if (!s) return;
  const sname = serverName();
  if (!sname) return;

  s.innerHTML = `<div class="file-move-modal" id="file-move-modal">
       <p class="t-caption">Move <code>${escapeHtml(sourceName)}</code> to:</p>
       <div class="file-picker">
         <button type="button" class="file-picker__select file-picker__root"
                 data-picker-select data-picker-path="">(server root)</button>
         <ul class="file-picker__children"
             hx-get="/servers/${encodeURIComponent(sname)}/files/tree?picker=1"
             hx-trigger="load"
             hx-swap="innerHTML"></ul>
       </div>
       <p class="t-caption file-move-modal__selection">
         Selected: <code data-move-selection>(none)</code>
       </p>
       <div class="file-move-modal__actions">
         <button type="button" class="file-action-form__btn" data-move-submit disabled>Move here</button>
         <button type="button" class="file-action-form__btn" data-move-cancel>Cancel</button>
       </div>
     </div>`;

  // Re-arm htmx so the picker's load-trigger fires and lazy-load on
  // sub-folders works inside the freshly-injected tree.
  if (window.htmx && window.htmx.process) window.htmx.process(s);

  const modal = s.querySelector("#file-move-modal");
  const selBox = s.querySelector("[data-move-selection]");
  const submit = s.querySelector("[data-move-submit]");
  const cancel = s.querySelector("[data-move-cancel]");
  let selected = null;

  // Selecting "(server root)" when no row is clicked: provide a
  // root-row affordance so the operator can move things into the root
  // even when the source already lives inside a subfolder. Add it as
  // the first picker entry.
  modal.addEventListener("click", (evt) => {
    const row = evt.target.closest && evt.target.closest("[data-picker-select]");
    if (!row || !modal.contains(row)) return;
    selected = row.dataset.pickerPath || "";
    selBox.textContent = selected === "" ? "(server root)" : selected;
    submit.disabled = false;
    modal.querySelectorAll("[data-picker-select]").forEach((b) => b.classList.remove("is-selected"));
    row.classList.add("is-selected");
  });

  // Re-process htmx whenever the picker swaps in new sub-children, so
  // their hx-get triggers stay wired.
  modal.addEventListener("htmx:afterSwap", () => {
    if (window.htmx && window.htmx.process) window.htmx.process(modal);
  });

  submit.addEventListener("click", async () => {
    if (submit.disabled || selected === null) return;
    await performMove(sourcePath, selected);
  });
  cancel.addEventListener("click", () => { s.innerHTML = ""; });
}

async function performMove(source, destDir) {
  const name = serverName();
  if (!name) return;
  const fd = new FormData();
  fd.append("source", source);
  fd.append("dest_dir", destDir);

  let resp;
  try {
    resp = await fetch(`/servers/${encodeURIComponent(name)}/files/move`, {
      method: "POST",
      body: fd,
    });
  } catch (err) {
    showError(`move failed: ${err.message}`);
    return;
  }

  if (!resp.ok) {
    showError(await errorMessageFor("move", resp));
    return;
  }

  const html = await resp.text();
  swapTreeAt(parentOf(source), html);
  // Slice 5 follow-up: if the destination is currently expanded in the
  // tree, refresh its listing too so the moved item appears without the
  // operator having to collapse and re-expand.
  await refreshTreeAt(destDir);
  const s = status();
  if (s) s.innerHTML = "";
  const t = tree();
  if (t && window.htmx && window.htmx.process) window.htmx.process(t);
}

async function refreshTreeAt(path) {
  const name = serverName();
  if (!name) return;
  const sel = path === ""
    ? "#file-tree"
    : `[data-upload-target][data-upload-path="${cssEscape(path)}"] > .file-tree__children`;
  const ul = document.querySelector(sel);
  if (!ul) return;  // Not currently visible — skip the round-trip.
  try {
    const resp = await fetch(
      `/servers/${encodeURIComponent(name)}/files/tree?path=${encodeURIComponent(path)}`
    );
    if (!resp.ok) return;
    ul.innerHTML = await resp.text();
    if (window.htmx && window.htmx.process) window.htmx.process(ul);
  } catch (_err) {
    // Best-effort refresh; fall back to operator manually re-expanding.
  }
}

// ---- multi-select + bulk delete/move (slice 5 PR 7) -----------------

const SELECTION = new Set();

function bulkToolbar() { return document.getElementById("file-bulk-toolbar"); }

function syncBulkUi() {
  const tb = bulkToolbar();
  if (!tb) return;
  tb.hidden = SELECTION.size === 0;
  const counter = tb.querySelector("[data-bulk-count]");
  if (counter) {
    counter.textContent = `${SELECTION.size} selected`;
  }
  // Reflect SELECTION in every visible checkbox — covers the case where
  // the operator selected something, then expanded a folder (htmx swap)
  // and the new DOM rows would otherwise come up unchecked.
  document.querySelectorAll("[data-select-path]").forEach((cb) => {
    const p = cb.dataset.selectPath || "";
    cb.checked = SELECTION.has(p);
  });
}

document.addEventListener("change", (evt) => {
  const cb = evt.target.closest && evt.target.closest("[data-select-path]");
  if (!cb) return;
  const p = cb.dataset.selectPath || "";
  if (cb.checked) SELECTION.add(p);
  else SELECTION.delete(p);
  syncBulkUi();
});

document.body.addEventListener("htmx:afterSwap", () => syncBulkUi());

document.addEventListener("click", (evt) => {
  const btn = evt.target.closest && evt.target.closest("[data-bulk-action]");
  if (!btn) return;
  evt.preventDefault();
  const action = btn.dataset.bulkAction;
  if (action === "clear") {
    SELECTION.clear();
    syncBulkUi();
    const s = status();
    if (s) s.innerHTML = "";
    return;
  }
  if (SELECTION.size === 0) return;
  if (action === "delete") showBulkDeleteConfirm();
  else if (action === "move") showBulkMoveModal();
});

function showBulkDeleteConfirm() {
  const s = status();
  if (!s) return;
  const paths = [...SELECTION];
  const sample = paths.slice(0, 6).map(escapeHtml).join(", ") +
    (paths.length > 6 ? `, … (${paths.length - 6} more)` : "");
  s.innerHTML = `<div class="file-delete-confirm file-delete-confirm--danger">
       <p class="t-caption">Delete ${paths.length} selected item${paths.length === 1 ? "" : "s"}? Recursive for folders.</p>
       <p class="t-caption"><code>${sample}</code></p>
       <p class="t-caption">Type <code>DELETE</code> to confirm:</p>
       <div class="file-delete-confirm__actions">
         <input type="text" autocomplete="off" data-bulk-confirm-input>
         <button type="button" class="file-delete-confirm__btn file-delete-confirm__btn--danger" data-bulk-confirm-submit disabled>Delete all</button>
         <button type="button" class="file-delete-confirm__btn" data-bulk-confirm-cancel>Cancel</button>
       </div>
     </div>`;

  const input = s.querySelector("[data-bulk-confirm-input]");
  const submit = s.querySelector("[data-bulk-confirm-submit]");
  const cancel = s.querySelector("[data-bulk-confirm-cancel]");

  if (input && submit) {
    input.addEventListener("input", () => {
      submit.disabled = input.value !== "DELETE";
    });
    input.focus();
  }
  submit.addEventListener("click", async () => {
    if (submit.disabled) return;
    await performBulkDelete(paths);
  });
  cancel.addEventListener("click", () => { s.innerHTML = ""; });
}

async function performBulkDelete(paths) {
  const name = serverName();
  if (!name) return;
  const fd = new FormData();
  for (const p of paths) fd.append("paths", p);
  fd.append("confirm", "DELETE");

  let resp;
  try {
    resp = await fetch(`/servers/${encodeURIComponent(name)}/files/bulk_delete`, {
      method: "POST",
      body: fd,
    });
  } catch (err) {
    showError(`bulk delete failed: ${err.message}`);
    return;
  }
  if (!resp.ok) {
    showError(await errorMessageFor("bulk delete", resp));
    return;
  }

  const html = await resp.text();
  // Multi-parent batches are flattened into a root-listing refresh.
  swapTreeAt("", html);
  SELECTION.clear();
  syncBulkUi();
  const s = status();
  if (s) s.innerHTML = "";
  const t = tree();
  if (t && window.htmx && window.htmx.process) window.htmx.process(t);
}

function showBulkMoveModal() {
  const s = status();
  if (!s) return;
  const sname = serverName();
  if (!sname) return;
  const sources = [...SELECTION];

  s.innerHTML = `<div class="file-move-modal" id="file-bulk-move-modal">
       <p class="t-caption">Move ${sources.length} selected item${sources.length === 1 ? "" : "s"} to:</p>
       <div class="file-picker">
         <button type="button" class="file-picker__select file-picker__root"
                 data-picker-select data-picker-path="">(server root)</button>
         <ul class="file-picker__children"
             hx-get="/servers/${encodeURIComponent(sname)}/files/tree?picker=1"
             hx-trigger="load"
             hx-swap="innerHTML"></ul>
       </div>
       <p class="t-caption file-move-modal__selection">
         Selected destination: <code data-move-selection>(none)</code>
       </p>
       <div class="file-move-modal__actions">
         <button type="button" class="file-action-form__btn" data-bulk-move-submit disabled>Move here</button>
         <button type="button" class="file-action-form__btn" data-bulk-move-cancel>Cancel</button>
       </div>
     </div>`;

  if (window.htmx && window.htmx.process) window.htmx.process(s);

  const modal = s.querySelector("#file-bulk-move-modal");
  const selBox = s.querySelector("[data-move-selection]");
  const submit = s.querySelector("[data-bulk-move-submit]");
  const cancel = s.querySelector("[data-bulk-move-cancel]");
  let selectedDest = null;

  modal.addEventListener("click", (evt) => {
    const row = evt.target.closest && evt.target.closest("[data-picker-select]");
    if (!row || !modal.contains(row)) return;
    selectedDest = row.dataset.pickerPath || "";
    selBox.textContent = selectedDest === "" ? "(server root)" : selectedDest;
    submit.disabled = false;
    modal.querySelectorAll("[data-picker-select]").forEach((b) => b.classList.remove("is-selected"));
    row.classList.add("is-selected");
  });
  modal.addEventListener("htmx:afterSwap", () => {
    if (window.htmx && window.htmx.process) window.htmx.process(modal);
  });
  submit.addEventListener("click", async () => {
    if (submit.disabled || selectedDest === null) return;
    await performBulkMove(sources, selectedDest);
  });
  cancel.addEventListener("click", () => { s.innerHTML = ""; });
}

async function performBulkMove(sources, destDir) {
  const name = serverName();
  if (!name) return;
  const fd = new FormData();
  for (const src of sources) fd.append("sources", src);
  fd.append("dest_dir", destDir);

  let resp;
  try {
    resp = await fetch(`/servers/${encodeURIComponent(name)}/files/bulk_move`, {
      method: "POST",
      body: fd,
    });
  } catch (err) {
    showError(`bulk move failed: ${err.message}`);
    return;
  }
  if (!resp.ok) {
    showError(await errorMessageFor("bulk move", resp));
    return;
  }

  const html = await resp.text();
  swapTreeAt("", html);
  SELECTION.clear();
  syncBulkUi();
  const s = status();
  if (s) s.innerHTML = "";
  const t = tree();
  if (t && window.htmx && window.htmx.process) window.htmx.process(t);
}

// ---- file search clear button (issue #67) ----------------------------

// Explicit × button beside the search input. Browsers render a native
// clear for type="search" inconsistently (Firefox doesn't), and even
// where it exists it skips firing `input` so the htmx-bound results
// pane stays stale. Dispatching `input` on click drives the existing
// `hx-trigger="input changed"` to re-query with an empty value, which
// clears #file-search-results.
(function () {
  const input = document.getElementById("file-search-input");
  const clearBtn = document.getElementById("file-search-clear");
  if (!input || !clearBtn) return;

  function sync() { clearBtn.hidden = !input.value; }

  input.addEventListener("input", sync);
  clearBtn.addEventListener("click", () => {
    input.value = "";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    clearBtn.hidden = true;
    input.focus();
  });
  input.addEventListener("keydown", (evt) => {
    if (evt.key === "Escape" && input.value) {
      evt.preventDefault();
      clearBtn.click();
    }
  });
  sync();
})();
