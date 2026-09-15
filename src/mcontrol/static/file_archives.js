// Archive actions use the file explorer's shared selection and tree helpers.
// Keep a dialog's inputs intact until the server has completed the operation.
(function () {
  let activeDialog = null;

  function archiveStem(path) {
    return path.split("/").pop().replace(/\.(zip|rar)$/i, "");
  }

  async function capabilities() {
    const resp = await fetch(`/servers/${encodeURIComponent(serverName())}/files/archive-capabilities`);
    if (!resp.ok) throw new Error(await errorMessageFor("Check archive support", resp));
    return resp.json();
  }

  function picker() {
    return `<details class="file-archive-dialog__picker"><summary>Choose an existing folder</summary>
      <div class="file-picker">
        <button type="button" class="file-picker__select file-picker__root"
                data-picker-select data-picker-path="">(server root)</button>
        <ul class="file-picker__children"
            hx-get="/servers/${encodeURIComponent(serverName())}/files/tree?picker=1"
            hx-trigger="load" hx-swap="innerHTML"></ul>
      </div></details>`;
  }

  function makeDialog(title, content) {
    if (activeDialog) {
      activeDialog.focus();
      return null;
    }
    const previousFocus = document.activeElement;
    const dialog = document.createElement("dialog");
    dialog.className = "file-archive-dialog";
    dialog.setAttribute("aria-labelledby", "file-archive-title");
    dialog.innerHTML = `<form class="file-archive-dialog__form">
      <h2 id="file-archive-title">${title}</h2>${content}
      <p class="t-caption t-muted" data-archive-support role="status">Checking archive support…</p>
      <p class="t-caption file-archive-dialog__error" data-archive-error role="alert" hidden></p>
      <p class="t-caption" data-archive-progress role="status" hidden></p>
      <div class="file-archive-dialog__actions">
        <button type="submit" class="btn btn--sm" data-archive-submit disabled>${title.startsWith("Compress") ? "Compress" : "Extract"}</button>
        <button type="button" class="btn btn--sm btn--ghost" data-archive-cancel>Cancel</button>
      </div></form>`;
    document.body.append(dialog);
    activeDialog = dialog;
    dialog.addEventListener("cancel", (evt) => {
      if (dialog.dataset.pending === "true") evt.preventDefault();
    });
    dialog.addEventListener("close", () => {
      activeDialog = null;
      dialog.remove();
      if (previousFocus && document.contains(previousFocus)) previousFocus.focus();
      else syncTreeTabindex();
    });
    dialog.querySelector("[data-archive-cancel]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (evt) => {
      const choice = evt.target.closest?.("[data-picker-select]");
      if (!choice || dialog.dataset.pending === "true") return;
      const input = dialog.querySelector("[name=dest_dir]");
      if (input) input.value = choice.dataset.pickerPath || "";
      dialog.querySelectorAll("[data-picker-select]").forEach((button) => {
        button.classList.toggle("is-selected", button === choice);
      });
    });
    dialog.showModal();
    if (window.htmx?.process) window.htmx.process(dialog);
    return dialog;
  }

  function showDialogError(dialog, message) {
    const error = dialog.querySelector("[data-archive-error]");
    error.textContent = message;
    error.hidden = false;
  }

  async function configure(dialog, kind, path) {
    const support = dialog.querySelector("[data-archive-support]");
    const submit = dialog.querySelector("[data-archive-submit]");
    try {
      const caps = await capabilities();
      if (!dialog.isConnected) return false;
      if (kind === "compress") {
        const rar = dialog.querySelector('option[value="rar"]');
        rar.disabled = !caps.rar_compress;
        support.textContent = caps.rar_compress
          ? "ZIP and RAR are available."
          : "RAR creation is unavailable. The server needs the licensed rar tool. ZIP is available.";
      } else {
        const available = /\.rar$/i.test(path) ? caps.rar_extract : caps.zip;
        support.textContent = available ? "The original archive will be kept. Existing files will not be replaced."
          : "RAR extraction is unavailable. The server needs a RAR extraction tool.";
        if (!available) return false;
      }
      submit.disabled = !caps.zip;
      return caps.zip;
    } catch (err) {
      if (dialog.isConnected) {
        support.textContent = "Archive support could not be checked.";
        showDialogError(dialog, err.message);
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "btn btn--sm";
        retry.textContent = "Check again";
        retry.addEventListener("click", async () => {
          retry.remove();
          dialog.querySelector("[data-archive-error]").hidden = true;
          await configure(dialog, kind, path);
        });
        support.append(" ", retry);
      }
      return false;
    }
  }

  // Refresh a visible ancestor when extraction creates a new folder, then
  // restore expanded folders discarded by that refresh. Search also re-queries.
  async function refreshArchives(destDir) {
    const expanded = [...document.querySelectorAll('#file-tree .file-tree__entry--dir[aria-expanded="true"]')]
      .map((row) => row.dataset.treePath);
    let target = destDir;
    while (target && !findTreeRow(target)) target = parentOf(target);
    await refreshTreeAt(target);
    for (const path of expanded.sort((a, b) => a.split("/").length - b.split("/").length)) {
      const row = findTreeRow(path);
      if (!row) continue;
      const children = row.querySelector(":scope > .file-tree__children");
      if (!children.children.length) await refreshTreeAt(path);
      row.setAttribute("aria-expanded", "true");
    }
    syncBulkUi();
    syncTreeTabindex();
    syncCurrentFile();
    const input = document.getElementById("file-search-input");
    if (input?.value && window.htmx?.ajax) {
      try {
        await window.htmx.ajax("GET", `/servers/${encodeURIComponent(serverName())}/files/search?q=${encodeURIComponent(input.value)}`,
          { target: "#file-search-results", swap: "innerHTML" });
      } catch (_err) { /* The explorer's existing error handler offers retry. */ }
    }
  }

  async function run(dialog, operation, formData) {
    if (dialog.dataset.pending === "true" || dialog.querySelector("[data-archive-submit]").disabled) return;
    const controls = [...dialog.querySelectorAll("button, input, select")];
    const priorDisabled = controls.map((control) => control.disabled);
    dialog.dataset.pending = "true";
    dialog.setAttribute("aria-busy", "true");
    controls.forEach((control) => { control.disabled = true; });
    dialog.querySelector("[data-archive-error]").hidden = true;
    const progress = dialog.querySelector("[data-archive-progress]");
    progress.textContent = operation === "compress" ? "Compressing selected items…" : "Extracting archive…";
    progress.hidden = false;
    try {
      const resp = await fetch(`/servers/${encodeURIComponent(serverName())}/files/${operation}`, {
        method: "POST", body: formData,
      });
      if (!resp.ok) throw new Error(await errorMessageFor(operation === "compress" ? "Compression" : "Extraction", resp));
      if (operation === "compress") {
        for (const path of formData.getAll("paths")) SELECTION.delete(path);
      }
      await refreshArchives(formData.get("dest_dir") || "");
      dialog.close();
    } catch (err) {
      showDialogError(dialog, err.message);
    } finally {
      if (dialog.isConnected) {
        dialog.dataset.pending = "false";
        dialog.removeAttribute("aria-busy");
        controls.forEach((control, index) => { control.disabled = priorDisabled[index]; });
        progress.hidden = true;
      }
    }
  }

  async function extract(path, here) {
    const parent = parentOf(path);
    const dest = here ? parent : (parent ? `${parent}/` : "") + archiveStem(path);
    const dialog = makeDialog(here ? "Extract here" : "Extract to folder", `
      <p class="t-caption">Archive: <code>${escapeHtml(path)}</code></p>
      ${here ? `<p class="t-caption">Destination: <code>${escapeHtml(parent || "(server root)")}</code></p>`
        : `<label class="file-archive-dialog__field">Destination folder
          <input name="dest_dir" type="text" value="${escapeHtml(dest)}" autocomplete="off" aria-describedby="archive-dest-help"></label>
          <p id="archive-dest-help" class="t-caption t-muted">Path from the server root. A new folder will be created if needed. Leave blank for the server root.</p>${picker()}`}`);
    if (!dialog) return;
    const submit = () => {
      const fd = new FormData();
      fd.append("path", path);
      fd.append("dest_dir", here ? dest : dialog.querySelector("[name=dest_dir]").value.trim());
      return run(dialog, "extract", fd);
    };
    dialog.querySelector("form").addEventListener("submit", (evt) => { evt.preventDefault(); submit(); });
    if (await configure(dialog, "extract", path) && here && dialog.isConnected) await submit();
  }

  async function compress() {
    const paths = [...SELECTION];
    if (!paths.length) return;
    const parents = new Set(paths.map(parentOf));
    const dest = parents.size === 1 ? parents.values().next().value : "";
    const stem = paths.length === 1 ? paths[0].split("/").pop().replace(/\.[^.]+$/, "") : "archive";
    const dialog = makeDialog("Compress selected items", `
      <p class="t-caption">${paths.length} selected item${paths.length === 1 ? "" : "s"}. The originals will be kept.</p>
      <label class="file-archive-dialog__field">Format
        <select name="format"><option value="zip">ZIP</option><option value="rar" disabled>RAR</option></select></label>
      <label class="file-archive-dialog__field">Archive name
        <input name="archive_name" type="text" value="${escapeHtml(stem || "archive")}.zip" required autocomplete="off" aria-describedby="archive-name-help"></label>
      <p id="archive-name-help" class="t-caption t-muted">One filename including .zip or .rar. Existing files will not be replaced.</p>
      <label class="file-archive-dialog__field">Destination folder
        <input name="dest_dir" type="text" value="${escapeHtml(dest)}" autocomplete="off" aria-describedby="archive-dest-help"></label>
      <p id="archive-dest-help" class="t-caption t-muted">Path from the server root. Leave blank for the server root.</p>${picker()}`);
    if (!dialog) return;
    const format = dialog.querySelector("[name=format]");
    const name = dialog.querySelector("[name=archive_name]");
    format.addEventListener("change", () => {
      name.value = name.value.replace(/\.(zip|rar)$/i, "") + "." + format.value;
      name.setCustomValidity("");
    });
    name.addEventListener("input", () => name.setCustomValidity(""));
    dialog.querySelector("form").addEventListener("submit", (evt) => {
      evt.preventDefault();
      if (/[\\/]/.test(name.value)) {
        name.setCustomValidity("Use one filename without folder separators.");
        name.reportValidity();
        return;
      }
      if (!name.value.toLowerCase().endsWith("." + format.value)) {
        name.setCustomValidity(`Use a .${format.value} filename for this format.`);
        name.reportValidity();
        return;
      }
      const fd = new FormData(dialog.querySelector("form"));
      fd.set("archive_name", name.value.trim());
      fd.set("dest_dir", fd.get("dest_dir").trim());
      for (const path of paths) fd.append("paths", path);
      run(dialog, "compress", fd);
    });
    await configure(dialog, "compress");
  }

  document.addEventListener("click", (evt) => {
    const action = evt.target.closest?.("[data-archive-extract]");
    if (action) {
      evt.preventDefault();
      extract(action.dataset.archivePath, action.dataset.archiveExtract === "here");
    } else if (evt.target.closest?.('[data-bulk-action="compress"]')) {
      evt.preventDefault();
      compress();
    }
  });

  document.addEventListener("contextmenu", (evt) => {
    const row = evt.target.closest?.("#file-tree .file-tree__entry");
    if (!row) return;
    const menu = row.querySelector(":scope > details.file-tree__menu");
    if (!menu) return;
    evt.preventDefault();
    menu.open = true;
    menu.querySelector("summary").focus({ preventScroll: true });
  });
})();
