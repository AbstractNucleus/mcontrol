// Shared focus-trap + lifecycle for overlay modal dialogs (issue #110).
//
// Every overlay modal (player-remove, trash-empty, trash-delete) is server-
// rendered into a slot (#player-modal, #trash-modal) by htmx, then removed
// by either a Cancel button, an Escape press, or a swap that replaces the
// slot. The three modals already carry role="dialog" + aria-modal +
// aria-labelledby; this module wires the behavioural half:
//
//   - move focus into the modal on open (first focusable, or the title
//     with tabindex=-1)
//   - cycle Tab/Shift+Tab within the modal's focusables (focus trap)
//   - close on Escape
//   - return focus to the element that opened the modal — falling back to
//     document.body if that element is gone (e.g. swapped-out trash row)
//
// Modal roots opt in by carrying [data-modal-root]. Cancel buttons opt in
// by carrying [data-modal-close]; htmx forms that close the modal by
// swapping its slot are handled by the slot's htmx:beforeSwap.

(function () {
  const FOCUSABLE = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled]):not([type=hidden])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  // trigger element keyed by modal-slot id, captured at request time so
  // we can restore focus when the modal closes.
  const triggers = new Map();

  function focusables(root) {
    return Array.from(root.querySelectorAll(FOCUSABLE))
      .filter((el) => !el.hasAttribute("hidden") && el.offsetParent !== null);
  }

  function focusFirst(root) {
    const items = focusables(root);
    if (items.length > 0) {
      items[0].focus();
      return;
    }
    // No focusables: fall back to the labelled title so SR users still
    // land somewhere meaningful.
    const labelId = root.getAttribute("aria-labelledby");
    const title = labelId ? root.querySelector(`#${CSS.escape(labelId)}`) : null;
    if (title) {
      title.setAttribute("tabindex", "-1");
      title.focus();
    }
  }

  function trapTab(evt, root) {
    if (evt.key !== "Tab") return;
    const items = focusables(root);
    if (items.length === 0) {
      evt.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (evt.shiftKey) {
      if (active === first || !root.contains(active)) {
        evt.preventDefault();
        last.focus();
      }
    } else if (active === last) {
      evt.preventDefault();
      first.focus();
    }
  }

  function closeModal(root) {
    const slot = root.parentElement;
    const slotId = slot ? slot.id : null;
    // Remove the modal from the DOM; htmx-driven closes (form submit that
    // swaps the slot) will hit this same path via the slot's beforeSwap.
    root.remove();
    restoreTrigger(slotId);
  }

  function restoreTrigger(slotId) {
    if (!slotId) return;
    const trigger = triggers.get(slotId);
    triggers.delete(slotId);
    if (trigger && document.contains(trigger) && typeof trigger.focus === "function") {
      trigger.focus();
    } else {
      document.body.focus?.();
    }
  }

  function initModal(root) {
    if (!root || root.dataset.modalInited === "1") return;
    root.dataset.modalInited = "1";

    root.addEventListener("keydown", (evt) => {
      if (evt.key === "Escape") {
        evt.preventDefault();
        closeModal(root);
        return;
      }
      trapTab(evt, root);
    });

    root.addEventListener("click", (evt) => {
      const closer = evt.target.closest && evt.target.closest("[data-modal-close]");
      if (!closer || !root.contains(closer)) return;
      // Anchor-tag closers may carry their own htmx-driven navigation;
      // don't preventDefault — just stash the trigger restore.
      // (Plain <button data-modal-close> just removes the modal.)
      if (closer.tagName === "BUTTON" && !closer.hasAttribute("hx-get") && !closer.hasAttribute("hx-post")) {
        evt.preventDefault();
        closeModal(root);
      }
    });

    focusFirst(root);
  }

  // Capture the element that opened a modal at request-issue time, before
  // htmx fires the request. Works for any trigger whose target points at
  // a known modal slot.
  document.body.addEventListener("htmx:beforeRequest", (evt) => {
    const target = evt.detail && evt.detail.target;
    if (!target || !target.id) return;
    if (target.id !== "player-modal" && target.id !== "trash-modal") return;
    const elt = evt.detail.elt || document.activeElement;
    if (elt && typeof elt.focus === "function") {
      triggers.set(target.id, elt);
    }
  });

  // After htmx swaps a modal into its slot, run the focus-trap setup. If
  // the slot was emptied (form submit swapped it back to ""), restore the
  // trigger.
  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const target = evt.detail && evt.detail.target;
    if (!target || !target.id) return;
    if (target.id !== "player-modal" && target.id !== "trash-modal") return;
    const root = target.querySelector(":scope > [data-modal-root]");
    if (root) {
      initModal(root);
    } else {
      // Slot was emptied by the swap → restore focus to whatever opened it.
      restoreTrigger(target.id);
    }
  });
})();
