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

  const body = await resp.text();

  if (resp.status === 409) {
    showConflict(body, () => uploadFiles(path, files, true));
    return;
  }
  if (!resp.ok) {
    showError(`upload failed: HTTP ${resp.status}`);
    return;
  }

  swapTreeAt(path, body);
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
    showError(`delete failed: HTTP ${resp.status}`);
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

  if (resp.status === 409) {
    showError(`already exists: ${dirname}`);
    return;
  }
  if (!resp.ok) {
    showError(`mkdir failed: HTTP ${resp.status}`);
    return;
  }

  const html = await resp.text();
  swapTreeAt(parentPath, html);
  const s = status();
  if (s) s.innerHTML = "";
  const t = tree();
  if (t && window.htmx && window.htmx.process) window.htmx.process(t);
}
