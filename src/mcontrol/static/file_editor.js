// CodeMirror 6 mount for the file-view pane.
//
// The Jinja partial ships a hidden <textarea data-file-editor> with the
// file content. After every htmx swap we look for unmounted textareas
// inside #file-view, mount a CodeMirror EditorView next to each, hide
// the textarea, and keep the textarea's value in sync with the editor
// document so the form submits the current contents.
//
// Custom modes: .properties + .toml (legacy-modes), .snbt (tiny inline
// parser), .json / .xml / .yaml (lezer-based lang-* packages).
// Everything else is plain text.

import { EditorView, basicSetup } from "codemirror";
import { EditorState } from "@codemirror/state";
import { keymap } from "@codemirror/view";
import { indentWithTab } from "@codemirror/commands";
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from "@codemirror/language";
import { tags } from "@lezer/highlight";
import { properties as propertiesMode } from "@codemirror/legacy-modes/mode/properties";
import { toml as tomlMode } from "@codemirror/legacy-modes/mode/toml";
import { json } from "@codemirror/lang-json";
import { xml } from "@codemirror/lang-xml";
import { yaml } from "@codemirror/lang-yaml";

// Minimal SNBT (stringified-NBT) tokenizer. JSON-like with type
// suffixes on numbers and unquoted keys/values. Good enough for syntax
// colour; not a parser.
const snbtParser = {
  startState() {
    return {};
  },
  token(stream) {
    if (stream.eatSpace()) return null;
    if (stream.match(/^"(?:\\.|[^"\\])*"/)) return "string";
    if (stream.match(/^'(?:\\.|[^'\\])*'/)) return "string";
    if (stream.match(/^-?\d+(?:\.\d+)?[bBsSlLfFdD]?\b/)) return "number";
    if (stream.match(/^(true|false)\b/)) return "atom";
    if (stream.match(/^[A-Za-z_][\w-]*/)) return "variableName";
    if (stream.match(/^[{}[\],:;]/)) return "punctuation";
    stream.next();
    return null;
  },
};

// Syntax colours resolve through tokens.css custom properties so the
// palette follows the active theme without remounting the editor.
const themeHighlight = HighlightStyle.define([
  { tag: tags.string, color: "var(--code-string)" },
  { tag: tags.number, color: "var(--code-number)" },
  { tag: [tags.keyword, tags.atom, tags.bool], color: "var(--code-keyword)" },
  { tag: [tags.propertyName, tags.variableName], color: "var(--code-property)" },
  { tag: tags.comment, color: "var(--code-comment)" },
  { tag: tags.punctuation, color: "var(--code-punctuation)" },
]);

// Unsaved-changes tracking: one editor mounts at a time (#file-view),
// so a module-level flag + view handle is sufficient.
let dirty = false;
let currentView = null;
let hintCounter = 0;

function languageFor(filename) {
  const lower = (filename || "").toLowerCase();
  if (lower.endsWith(".properties")) {
    return StreamLanguage.define(propertiesMode);
  }
  if (lower.endsWith(".snbt")) {
    return StreamLanguage.define(snbtParser);
  }
  if (lower.endsWith(".json")) {
    return json();
  }
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) {
    return yaml();
  }
  if (lower.endsWith(".toml")) {
    return StreamLanguage.define(tomlMode);
  }
  if (lower.endsWith(".xml")) {
    return xml();
  }
  return null;
}

function mountEditor(textarea) {
  if (textarea.dataset.fileEditorMounted === "1") return;
  textarea.dataset.fileEditorMounted = "1";
  // Fresh mount = clean doc. Also covers confirmed discards and the
  // conflict banner's Reload, which both remount the editor. Exception:
  // a 409 remount ships the operator's *pending* content alongside the
  // conflict banner; that doc is not on disk, so it stays dirty.
  dirty = !!document.getElementById("file-conflict");

  const lang = languageFor(textarea.dataset.fileName);
  const saveKeymap = {
    key: "Mod-s",
    run: () => {
      const form = textarea.closest("[data-file-editor-form]");
      if (form) form.requestSubmit();
      return true;
    },
  };
  const hintId = `file-editor-tab-hint-${++hintCounter}`;
  const extensions = [
    basicSetup,
    keymap.of([saveKeymap, indentWithTab]),
    syntaxHighlighting(themeHighlight),
    EditorView.contentAttributes.of({ "aria-describedby": hintId }),
    EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        textarea.value = update.state.doc.toString();
        dirty = true;
      }
    }),
  ];
  if (lang) extensions.push(lang);

  const state = EditorState.create({
    doc: textarea.value,
    extensions,
  });
  const view = new EditorView({ state });
  textarea.parentNode.insertBefore(view.dom, textarea);
  view.dom.classList.add("file-editor__cm");
  // indentWithTab traps Tab; advertise the standard escape hatch to
  // assistive tech via the content element's aria-describedby.
  const hint = document.createElement("span");
  hint.id = hintId;
  hint.className = "visually-hidden";
  hint.textContent = "Press Escape, then Tab to leave the editor";
  textarea.parentNode.insertBefore(hint, textarea);
  textarea.style.display = "none";
  currentView = view;
}

function mountAll(root) {
  if (!root || !root.querySelectorAll) return;
  root
    .querySelectorAll("[data-file-editor]")
    .forEach((ta) => mountEditor(ta));
}

document.body.addEventListener("htmx:afterSettle", (evt) => {
  mountAll(evt.target);
});

// Destroy the outgoing EditorView before a swap replaces #file-view's
// content; otherwise every file-open leaks the doc buffer plus a
// document-level event listener per abandoned view.
document.body.addEventListener("htmx:beforeSwap", (evt) => {
  const target = evt.detail && evt.detail.target;
  if (!currentView || !target || !target.contains(currentView.dom)) return;
  currentView.destroy();
  currentView = null;
});

// Clear the dirty flag on a successful save. Document-level (not bound
// to the form) because the conflict banner's Overwrite button POSTs
// /files/save via its own hx-post outside the form.
document.body.addEventListener("htmx:afterRequest", (evt) => {
  const path = evt.detail.pathInfo && evt.detail.pathInfo.requestPath;
  if (evt.detail.successful && path && path.includes("/files/save")) {
    dirty = false;
  }
});

// Unsaved-changes guard. Only GETs targeting #file-view (tree links,
// search results, conflict Reload) destroy pending edits; POSTs (Save,
// Overwrite) must never prompt.
document.body.addEventListener("htmx:confirm", (evt) => {
  if (!dirty) return;
  const d = evt.detail;
  if (!d.target || d.target.id !== "file-view" || d.verb !== "get") return;
  if (!window.confirm("Discard unsaved changes?")) evt.preventDefault();
});

window.addEventListener("beforeunload", (evt) => {
  if (dirty) evt.preventDefault();
});

// Cover the case where the partial is already in the DOM at page load
// (server-rendered without going through htmx, e.g. a direct GET).
mountAll(document);
