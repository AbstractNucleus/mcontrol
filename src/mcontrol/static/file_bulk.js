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
  // Reflect SELECTION in every visible checkbox. covers the case where
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
// Runs on the click event. by the time it fires, cb.checked is already
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
         <button type="button" class="file-delete-confirm__btn file-delete-confirm__btn--danger" data-bulk-confirm-submit disabled>Delete all <span class="htmx-indicator btn-spinner" aria-hidden="true"></span></button>
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
    submit.classList.add("htmx-request");
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
         <button type="button" class="file-action-form__btn" data-bulk-move-submit disabled>Move here <span class="htmx-indicator btn-spinner" aria-hidden="true"></span></button>
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
    submit.classList.add("htmx-request");
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

