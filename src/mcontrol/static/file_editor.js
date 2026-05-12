// CodeMirror 6 mount for the file-view pane.
//
// The Jinja partial ships a hidden <textarea data-file-editor> with the
// file content. After every htmx swap we look for unmounted textareas
// inside #file-view, mount a CodeMirror EditorView next to each, hide
// the textarea, and keep the textarea's value in sync with the editor
// document so the form submits the current contents.
//
// Custom modes: .properties (legacy-modes), .snbt (tiny inline parser).
// Everything else is plain text.

import { EditorView, basicSetup } from "codemirror";
import { EditorState } from "@codemirror/state";
import { keymap } from "@codemirror/view";
import { indentWithTab } from "@codemirror/commands";
import { StreamLanguage } from "@codemirror/language";
import { properties as propertiesMode } from "@codemirror/legacy-modes/mode/properties";

// Minimal SNBT (stringified-NBT) tokenizer — JSON-like with type
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

function languageFor(filename) {
  const lower = (filename || "").toLowerCase();
  if (lower.endsWith(".properties")) {
    return StreamLanguage.define(propertiesMode);
  }
  if (lower.endsWith(".snbt")) {
    return StreamLanguage.define(snbtParser);
  }
  return null;
}

function mountEditor(textarea) {
  if (textarea.dataset.fileEditorMounted === "1") return;
  textarea.dataset.fileEditorMounted = "1";

  const lang = languageFor(textarea.dataset.fileName);
  const saveKeymap = {
    key: "Mod-s",
    run: () => {
      const form = textarea.closest("[data-file-editor-form]");
      if (form) form.requestSubmit();
      return true;
    },
  };
  const extensions = [
    basicSetup,
    keymap.of([saveKeymap, indentWithTab]),
    EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        textarea.value = update.state.doc.toString();
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
  textarea.style.display = "none";
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

// Cover the case where the partial is already in the DOM at page load
// (server-rendered without going through htmx, e.g. a direct GET).
mountAll(document);
