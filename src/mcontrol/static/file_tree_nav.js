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
          // Already open. move focus to first child if any.
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
// row. Capture the focused path before the swap and restore after. to
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
