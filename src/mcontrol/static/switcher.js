// Ctrl/Cmd+K quick switcher.
//
// Zero routes, zero markup templates: the palette is built from data the
// sidebar already renders on every page (nav links + server rows with
// state dots). Collapsed sidebars keep the list in the DOM (display:none),
// so the data source survives collapse. Type to filter, ArrowUp/Down to
// move, Enter to navigate, Escape to close.
(function () {
  "use strict";

  var overlay = null;
  var listEl = null;
  var inputEl = null;
  var matches = [];
  var selected = 0;
  var opener = null;

  function collectTargets() {
    var targets = [];
    document.querySelectorAll(".sidebar__nav-link").forEach(function (a) {
      var label = a.querySelector(".sidebar__nav-label");
      var name = label ? label.textContent.trim() : (a.getAttribute("title") || "").trim();
      if (name) targets.push({ name: name, href: a.getAttribute("href"), state: null });
    });
    document.querySelectorAll(".sidebar__server").forEach(function (a) {
      var nameEl = a.querySelector(".sidebar__server-name");
      if (!nameEl) return;
      var state = null;
      var dot = a.querySelector(".sidebar__server-dot");
      if (dot) {
        dot.classList.forEach(function (cls) {
          var idx = cls.indexOf("dot--");
          if (idx !== -1) state = cls.slice(idx + 5);
        });
      }
      targets.push({ name: nameEl.textContent.trim(), href: a.getAttribute("href"), state: state });
    });
    return targets;
  }

  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
    listEl = null;
    inputEl = null;
    if (opener && document.contains(opener) && typeof opener.focus === "function") {
      opener.focus();
    }
    opener = null;
  }

  function navigate() {
    var target = matches[selected];
    if (target) window.location.href = target.href;
  }

  function renderList(filter) {
    var all = collectTargets();
    var q = filter.trim().toLowerCase();
    matches = q
      ? all.filter(function (t) { return t.name.toLowerCase().indexOf(q) !== -1; })
      : all;
    if (selected >= matches.length) selected = Math.max(0, matches.length - 1);

    listEl.textContent = "";
    if (!matches.length) {
      var empty = document.createElement("li");
      empty.className = "switcher__empty";
      empty.textContent = "No matches";
      listEl.appendChild(empty);
      return;
    }
    matches.forEach(function (t, i) {
      var li = document.createElement("li");
      li.className = "switcher__item" + (i === selected ? " is-selected" : "");
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === selected ? "true" : "false");
      var dot = document.createElement("span");
      dot.className = "switcher__dot" +
        (t.state ? " sidebar__server-dot sidebar__server-dot--" + t.state : "");
      dot.setAttribute("aria-hidden", "true");
      var name = document.createElement("span");
      name.className = "switcher__name";
      name.textContent = t.name;
      li.appendChild(dot);
      li.appendChild(name);
      li.addEventListener("mousedown", function (evt) {
        evt.preventDefault();
        selected = i;
        navigate();
      });
      listEl.appendChild(li);
    });
  }

  function open() {
    if (overlay) return;
    selected = 0;
    opener = document.activeElement;

    overlay = document.createElement("div");
    overlay.className = "switcher";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Quick switcher");

    var panel = document.createElement("div");
    panel.className = "switcher__panel";

    inputEl = document.createElement("input");
    inputEl.type = "text";
    inputEl.className = "switcher__input";
    inputEl.placeholder = "Jump to server or page…";
    inputEl.setAttribute("aria-label", "Jump to server or page");
    inputEl.autocomplete = "off";

    listEl = document.createElement("ul");
    listEl.className = "switcher__list";
    listEl.setAttribute("role", "listbox");

    panel.appendChild(inputEl);
    panel.appendChild(listEl);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    inputEl.addEventListener("input", function () {
      selected = 0;
      renderList(inputEl.value);
    });
    inputEl.addEventListener("keydown", function (evt) {
      if (evt.key === "ArrowDown") {
        selected = Math.min(selected + 1, matches.length - 1);
        renderList(inputEl.value);
        evt.preventDefault();
      } else if (evt.key === "ArrowUp") {
        selected = Math.max(selected - 1, 0);
        renderList(inputEl.value);
        evt.preventDefault();
      } else if (evt.key === "Enter") {
        navigate();
        evt.preventDefault();
      }
    });
    overlay.addEventListener("mousedown", function (evt) {
      if (evt.target === overlay) close();
    });

    renderList("");
    inputEl.focus();
  }

  document.addEventListener("keydown", function (evt) {
    if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === "k") {
      evt.preventDefault();
      if (overlay) close(); else open();
      return;
    }
    if (evt.key === "Escape" && overlay) {
      evt.preventDefault();
      close();
    }
  });
})();
