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

  // XHR (not fetch) so we get upload.onprogress for the progress indicator
  // (issue #59). Modpack assets are routinely hundreds of MB; without
  // progress the operator sees no feedback during transit. Multi-file
  // batches report aggregate progress across the multipart body — adequate
  // per the issue brief.
  const xhr = new XMLHttpRequest();
  const progress = showUploadProgress(() => xhr.abort());
  const result = await new Promise((resolve) => {
    xhr.upload.addEventListener("progress", (evt) => {
      if (evt.lengthComputable) progress.update(evt.loaded, evt.total);
    });
    xhr.addEventListener("load", () => resolve({ kind: "done" }));
    xhr.addEventListener("error", () => resolve({ kind: "error", message: "network error" }));
    xhr.addEventListener("abort", () => resolve({ kind: "abort" }));
    xhr.open("POST", `/servers/${encodeURIComponent(name)}/files/upload`);
    xhr.send(fd);
  });

  if (result.kind === "abort") {
    const s = status();
    if (s) s.innerHTML = "";
    return;
  }
  if (result.kind === "error") {
    showError(`upload failed: ${result.message}`);
    return;
  }

  if (xhr.status === 409) {
    showConflict(xhr.responseText, () => uploadFiles(path, files, true));
    return;
  }
  if (xhr.status < 200 || xhr.status >= 300) {
    showError(errorMessageForXhr("upload", xhr));
    return;
  }

  swapTreeAt(path, xhr.responseText);
  const s = status();
  if (s) s.innerHTML = "";
  // Re-arm htmx for the freshly-injected tree subtree (lazy hx-get on
  // any newly-listed subfolders, click-to-view on files).
  const t = tree();
  if (t && window.htmx && window.htmx.process) window.htmx.process(t);
}

function showUploadProgress(onCancel) {
  const s = status();
  if (!s) return { update() {} };
  s.innerHTML = `<div class="file-upload-progress" id="file-upload-progress">
       <p class="t-caption file-upload-progress__caption" data-upload-caption>Uploading… 0%</p>
       <div class="file-upload-progress__bar">
         <div class="file-upload-progress__fill" data-upload-fill style="width: 0%"></div>
       </div>
       <div class="file-upload-progress__actions">
         <button type="button" class="file-action-form__btn" data-upload-cancel>Cancel</button>
       </div>
     </div>`;
  const caption = s.querySelector("[data-upload-caption]");
  const fill = s.querySelector("[data-upload-fill]");
  const cancel = s.querySelector("[data-upload-cancel]");
  cancel.addEventListener("click", () => { onCancel(); });
  return {
    update(loaded, total) {
      const pct = total > 0 ? Math.floor((loaded / total) * 100) : 0;
      if (fill) fill.style.width = `${pct}%`;
      if (caption) caption.textContent = `Uploading… ${formatBytes(loaded)} / ${formatBytes(total)} (${pct}%)`;
    },
  };
}

function formatBytes(n) {
  if (!Number.isFinite(n) || n < 0) return "?";
  const units = ["B", "KB", "MB", "GB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${i === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

// XHR equivalent of errorMessageFor: surface backend `detail` when
// available, falling back to the status code.
function errorMessageForXhr(verb, xhr) {
  try {
    const data = JSON.parse(xhr.responseText);
    if (data && typeof data.detail === "string" && data.detail) {
      return `${verb} failed: ${data.detail}`;
    }
  } catch (_err) { /* not JSON — fall through */ }
  return `${verb} failed: HTTP ${xhr.status}`;
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
// Anchor for Shift+click range selection (issue #58). Updated on every
// affirmative checkbox toggle (mouse or keyboard); not cleared on
// unselect so Finder-style "click A, click B, shift+click C" keeps A
// as the anchor.
let LAST_SELECTED_PATH = null;

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
  if (cb.checked) {
    SELECTION.add(p);
    LAST_SELECTED_PATH = p;
  } else {
    SELECTION.delete(p);
  }
  syncBulkUi();
});

// Issue #58: Shift+click on a checkbox selects every entry in visible
// DOM order between the anchor and the clicked checkbox (inclusive).
// Subtraction-on-shift is intentionally not supported (matches Finder).
// Runs on the click event — by the time it fires, cb.checked is already
// the post-toggle state, and modifier keys are available.
document.addEventListener("click", (evt) => {
  if (!evt.shiftKey) return;
  const cb = evt.target.closest && evt.target.closest("[data-select-path]");
  if (!cb) return;
  if (LAST_SELECTED_PATH === null) return;
  const p = cb.dataset.selectPath || "";
  if (p === LAST_SELECTED_PATH) return;
  // The native click has already toggled cb; for shift-range we always
  // additively select, so force cb checked even if the click unchecked it.
  cb.checked = true;
  const all = Array.from(document.querySelectorAll("[data-select-path]"));
  const ai = all.findIndex((c) => (c.dataset.selectPath || "") === LAST_SELECTED_PATH);
  const bi = all.indexOf(cb);
  if (ai < 0 || bi < 0) return;
  const lo = Math.min(ai, bi);
  const hi = Math.max(ai, bi);
  for (let i = lo; i <= hi; i++) {
    const c = all[i];
    c.checked = true;
    SELECTION.add(c.dataset.selectPath || "");
  }
  LAST_SELECTED_PATH = p;
  syncBulkUi();
});

// Issue #58: Ctrl/Cmd+click on a file or symlink name toggles its
// checkbox instead of opening the file. Capture phase so it preempts
// the htmx click handler attached on the link itself.
document.addEventListener("click", (evt) => {
  if (!(evt.ctrlKey || evt.metaKey)) return;
  const link = evt.target.closest && evt.target.closest(
    ".file-tree__entry--file > a, .file-tree__entry--symlink > a"
  );
  if (!link) return;
  const row = link.closest(".file-tree__entry");
  if (!row) return;
  const cb = row.querySelector(":scope > [data-select-path]");
  if (!cb) return;
  evt.preventDefault();
  evt.stopPropagation();
  cb.checked = !cb.checked;
  cb.dispatchEvent(new Event("change", { bubbles: true }));
}, true);

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

  // Refresh only the unique parent subtrees of the deleted paths;
  // refreshTreeAt is a no-op for parents that aren't currently expanded,
  // so unrelated expanded subtrees keep their state.
  const parents = new Set(paths.map(parentOf));
  await Promise.all([...parents].map(refreshTreeAt));
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

  // Refresh each source parent and the destination; refreshTreeAt skips
  // any subtree that isn't currently expanded, so unrelated expansions
  // are preserved.
  const targets = new Set(sources.map(parentOf));
  targets.add(destDir);
  await Promise.all([...targets].map(refreshTreeAt));
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

// ---- View-pane breadcrumb (issue #61) -------------------------------
//
// Each clickable breadcrumb segment carries `data-breadcrumb-path` with
// the absolute (relative to server root) path of that directory. The
// tree's lazy-load is `hx-trigger="click once"` on each dir's toggle
// button, so to reveal a deep segment we walk top-down: for every
// ancestor that isn't already rendered in the DOM, click its toggle and
// wait for the htmx swap. Once the target row exists, scroll it in.

function findTreeRow(path) {
  if (!path) return null;
  return document.querySelector(
    `#file-tree [data-upload-target][data-upload-path="${cssEscape(path)}"]`
  );
}

function waitForChildren(parentRow) {
  // Resolve once the parent's <ul.file-tree__children> has been
  // populated by htmx. Single afterSwap listener; falls back after a
  // generous timeout so a failed fetch can't hang the click handler.
  return new Promise((resolve) => {
    const children = parentRow.querySelector(":scope > .file-tree__children");
    if (children && children.children.length > 0) { resolve(); return; }
    const onSwap = (evt) => {
      if (!children) return;
      if (evt.target === children || children.contains(evt.target)) {
        document.body.removeEventListener("htmx:afterSwap", onSwap);
        resolve();
      }
    };
    document.body.addEventListener("htmx:afterSwap", onSwap);
    setTimeout(() => {
      document.body.removeEventListener("htmx:afterSwap", onSwap);
      resolve();
    }, 2000);
  });
}

async function revealBreadcrumb(path) {
  if (!path) return;
  const segments = path.split("/").filter(Boolean);
  let accum = "";
  for (let i = 0; i < segments.length; i++) {
    accum = accum ? `${accum}/${segments[i]}` : segments[i];
    let row = findTreeRow(accum);
    if (!row) {
      // Closest rendered ancestor needs its toggle clicked so htmx
      // lazy-loads the path down to this segment.
      const parentPath = segments.slice(0, i).join("/");
      const parentRow = parentPath ? findTreeRow(parentPath) : document.getElementById("file-tree");
      if (!parentRow) return;
      const toggle = parentPath
        ? parentRow.querySelector(":scope > .file-tree__toggle")
        : null;
      if (toggle) toggle.click();
      await waitForChildren(parentRow);
      row = findTreeRow(accum);
      if (!row) return;
    }
  }
  const target = findTreeRow(path);
  if (target) target.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

document.addEventListener("click", (evt) => {
  const seg = evt.target.closest && evt.target.closest("[data-breadcrumb-path]");
  if (!seg) return;
  evt.preventDefault();
  revealBreadcrumb(seg.dataset.breadcrumbPath || "");
});

// ---- Ctrl/Cmd+P → focus filename search (issue #62) -----------------
//
// Slice 5 framed the search input as "Cmd-P-style" but never wired the
// shortcut. Bind on document so it works regardless of current focus
// (including from inside the file editor). No-op when the search input
// isn't on the page so this stays safe to ship in the shared JS file.

let searchPreviousFocus = null;

document.addEventListener("keydown", (evt) => {
  if (evt.key !== "p" && evt.key !== "P") return;
  if (!(evt.ctrlKey || evt.metaKey)) return;
  if (evt.altKey || evt.shiftKey) return;
  const input = document.getElementById("file-search-input");
  if (!input) return;
  evt.preventDefault();
  searchPreviousFocus = document.activeElement;
  input.focus();
  input.select();
});

document.addEventListener("keydown", (evt) => {
  if (evt.key !== "Escape") return;
  const input = document.getElementById("file-search-input");
  if (!input || document.activeElement !== input) return;
  evt.preventDefault();
  const prev = searchPreviousFocus;
  searchPreviousFocus = null;
  if (prev && prev !== input && typeof prev.focus === "function" && document.contains(prev)) {
    prev.focus();
  } else {
    input.blur();
  }
});

// ---- WAI-ARIA tree keyboard nav + focus restore (issue #63) ----------
//
// Roving-tabindex pattern: exactly one tree row carries tabindex=0; the
// rest carry tabindex=-1. Arrow keys move focus through *visible* rows
// (rows inside a collapsed parent are skipped). Enter activates the row
// (open file / toggle dir). Space toggles the row's checkbox, composing
// with the SELECTION model and #58's Shift+click range. Right expands /
// enters a dir; Left collapses or moves to the parent.

function treeRoot() { return document.getElementById("file-tree"); }

function isCollapsedAncestor(row, root) {
  let p = row.parentElement;
  while (p && p !== root) {
    if (p.classList && p.classList.contains("file-tree__children")) {
      const dir = p.parentElement;
      if (dir && dir.getAttribute("aria-expanded") === "false") return true;
    }
    p = p.parentElement;
  }
  return false;
}

function visibleTreeRows() {
  const root = treeRoot();
  if (!root) return [];
  return Array.from(root.querySelectorAll(".file-tree__entry"))
    .filter((row) => !isCollapsedAncestor(row, root));
}

function setRovingTabindex(target) {
  const root = treeRoot();
  if (!root) return;
  root.querySelectorAll(".file-tree__entry").forEach((row) => {
    row.tabIndex = row === target ? 0 : -1;
  });
}

function focusTreeRow(row) {
  if (!row) return;
  setRovingTabindex(row);
  row.focus();
}

function rowIsDir(row) { return row.classList.contains("file-tree__entry--dir"); }
function rowChildrenList(row) {
  return row.querySelector(":scope > .file-tree__children");
}
function rowToggle(row) {
  return row.querySelector(":scope > .file-tree__toggle");
}
function rowLink(row) {
  return row.querySelector(":scope > a");
}
function rowCheckbox(row) {
  return row.querySelector(":scope > [data-select-path]");
}
function rowParent(row) {
  const root = treeRoot();
  let p = row.parentElement;
  while (p && p !== root) {
    if (p.classList.contains("file-tree__children")) {
      const dir = p.parentElement;
      if (dir && dir.classList.contains("file-tree__entry")) return dir;
    }
    p = p.parentElement;
  }
  return null;
}

function expandDir(row) {
  if (!rowIsDir(row)) return false;
  const kids = rowChildrenList(row);
  if (row.getAttribute("aria-expanded") === "true") return false;
  // First expansion: htmx lazy-loads via the toggle button.
  if (kids && kids.children.length === 0) {
    const toggle = rowToggle(row);
    if (toggle) toggle.click();
  }
  row.setAttribute("aria-expanded", "true");
  return true;
}

function collapseDir(row) {
  if (!rowIsDir(row)) return false;
  if (row.getAttribute("aria-expanded") !== "true") return false;
  row.setAttribute("aria-expanded", "false");
  return true;
}

// Initial roving-tabindex setup + after every htmx swap that touches
// the tree: ensure one row has tabindex=0 (the previously-active path
// if any, otherwise the first visible row). Newly-rendered dir rows
// already carry aria-expanded="false" from the template; mark dirs
// that have populated children as expanded so the keyboard model
// reflects the real DOM state.
function syncTreeTabindex() {
  const root = treeRoot();
  if (!root) return;
  const rows = visibleTreeRows();
  if (rows.length === 0) return;
  const current = root.querySelector('.file-tree__entry[tabindex="0"]');
  if (current && rows.includes(current)) return;
  setRovingTabindex(rows[0]);
}

document.addEventListener("keydown", (evt) => {
  const root = treeRoot();
  if (!root) return;
  const row = evt.target.closest && evt.target.closest(".file-tree__entry");
  if (!row || !root.contains(row)) return;
  // Don't hijack typing inside form controls within the tree (none
  // currently, but cheap insurance against future <input>s in rows).
  const tag = evt.target.tagName;
  if (tag === "INPUT" && evt.target.type === "text") return;

  const rows = visibleTreeRows();
  const idx = rows.indexOf(row);
  switch (evt.key) {
    case "ArrowDown":
      if (idx < rows.length - 1) {
        evt.preventDefault();
        focusTreeRow(rows[idx + 1]);
      }
      return;
    case "ArrowUp":
      if (idx > 0) {
        evt.preventDefault();
        focusTreeRow(rows[idx - 1]);
      }
      return;
    case "ArrowRight":
      if (rowIsDir(row)) {
        evt.preventDefault();
        if (row.getAttribute("aria-expanded") === "true") {
          // Already open — move focus to first child if any.
          const kids = rowChildrenList(row);
          const first = kids && kids.querySelector(":scope > .file-tree__entry");
          if (first) focusTreeRow(first);
        } else {
          expandDir(row);
          // Children may load async; afterSwap handler re-syncs.
        }
      }
      return;
    case "ArrowLeft": {
      evt.preventDefault();
      if (rowIsDir(row) && row.getAttribute("aria-expanded") === "true") {
        collapseDir(row);
      } else {
        const parent = rowParent(row);
        if (parent) focusTreeRow(parent);
      }
      return;
    }
    case "Enter": {
      evt.preventDefault();
      if (rowIsDir(row)) {
        if (row.getAttribute("aria-expanded") === "true") collapseDir(row);
        else expandDir(row);
      } else {
        const link = rowLink(row);
        if (link) link.click();
      }
      return;
    }
    case " ":
    case "Spacebar": {
      evt.preventDefault();
      const cb = rowCheckbox(row);
      if (!cb) return;
      cb.checked = !cb.checked;
      cb.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }
    default:
      return;
  }
});

// Track focus on click so the roving anchor follows pointer interaction.
document.addEventListener("focusin", (evt) => {
  const root = treeRoot();
  if (!root) return;
  const row = evt.target.closest && evt.target.closest(".file-tree__entry");
  if (!row || !root.contains(row)) return;
  // Only update tabindex if focus came directly to the row (not via
  // a nested focusable like the menu summary), to avoid stealing the
  // tabindex anchor away from where the operator was navigating.
  if (evt.target === row) setRovingTabindex(row);
});

// ---- Popover (<details>) keyboard nav (issue #63) --------------------

document.addEventListener("keydown", (evt) => {
  const det = evt.target.closest && evt.target.closest("details.file-tree__menu[open]");
  if (!det) return;
  const summary = det.querySelector(":scope > .file-tree__menu-trigger");
  const items = Array.from(det.querySelectorAll(".file-tree__menu-item"));
  if (evt.key === "Escape") {
    evt.preventDefault();
    det.open = false;
    if (summary) summary.focus();
    return;
  }
  if (evt.key === "ArrowDown" || evt.key === "ArrowUp") {
    if (items.length === 0) return;
    evt.preventDefault();
    const onSummary = evt.target === summary;
    const cur = onSummary ? -1 : items.indexOf(evt.target);
    const dir = evt.key === "ArrowDown" ? 1 : -1;
    let nx = cur + dir;
    if (nx < 0) nx = items.length - 1;
    if (nx >= items.length) nx = 0;
    items[nx].focus();
  }
});

// ---- Tree focus restoration after htmx swap (issue #63) --------------
//
// htmx replaces the matched element's children, discarding any focused
// row. Capture the focused path before the swap and restore after — to
// the same path if it still exists, otherwise to the closest surviving
// ancestor, otherwise to the first visible row.

let preSwapFocusPath = null;
let preSwapHadFocus = false;

document.body.addEventListener("htmx:beforeSwap", (evt) => {
  const root = treeRoot();
  if (!root) return;
  const active = document.activeElement;
  if (!active || !root.contains(active)) {
    preSwapHadFocus = false;
    preSwapFocusPath = null;
    return;
  }
  const row = active.closest(".file-tree__entry");
  preSwapHadFocus = true;
  preSwapFocusPath = row ? (row.dataset.treePath || "") : null;
  // Only restore if the swap target is inside the tree.
  if (!evt.detail || !evt.detail.target || !root.contains(evt.detail.target)) {
    preSwapHadFocus = false;
  }
});

document.body.addEventListener("htmx:afterSwap", () => {
  const root = treeRoot();
  if (!root) return;
  syncTreeTabindex();
  if (!preSwapHadFocus) return;
  const wanted = preSwapFocusPath;
  preSwapHadFocus = false;
  preSwapFocusPath = null;
  let target = null;
  if (wanted) {
    target = root.querySelector(`.file-tree__entry[data-tree-path="${cssEscape(wanted)}"]`);
    if (!target) {
      // Walk up the path looking for a surviving ancestor.
      const segs = wanted.split("/");
      while (segs.length > 1 && !target) {
        segs.pop();
        target = root.querySelector(
          `.file-tree__entry[data-tree-path="${cssEscape(segs.join("/"))}"]`
        );
      }
    }
  }
  if (!target) {
    const rows = visibleTreeRows();
    target = rows[0] || null;
  }
  if (target) focusTreeRow(target);
});

// First paint: when the root tree loads its top-level entries, install
// the roving tabindex. htmx:afterSwap above already handles the load
// case; this also covers cases where the JS runs after the initial swap.
document.addEventListener("DOMContentLoaded", () => syncTreeTabindex());

// Mark a dir as aria-expanded=true after its first lazy-load completes.
document.body.addEventListener("htmx:afterSwap", (evt) => {
  const tgt = evt.detail && evt.detail.target;
  if (!tgt || !tgt.classList || !tgt.classList.contains("file-tree__children")) return;
  const dir = tgt.parentElement;
  if (dir && dir.classList.contains("file-tree__entry--dir")) {
    dir.setAttribute("aria-expanded", "true");
  }
});
