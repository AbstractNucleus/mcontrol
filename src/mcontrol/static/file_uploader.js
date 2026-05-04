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
function status() { return document.getElementById("file-upload-status"); }
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
  s.innerHTML = `<div class="file-upload-error t-caption">${msg}</div>`;
}
