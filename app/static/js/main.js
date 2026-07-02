/**
 * Small helpers used across the app.
 *
 * Kept dependency-free and self-contained so the base template loads
 * ~2KB total. All behaviors are additive; the app works without JS.
 */

// ---------------------------------------------------------- Toast dismissal

function initToasts() {
  document.querySelectorAll(".flash").forEach((el) => {
    // Skip auto-dismiss for warnings/errors — user should acknowledge.
    if (el.classList.contains("flash--danger") || el.classList.contains("flash--warning")) return;
    setTimeout(() => {
      el.style.transition = "opacity 300ms ease, transform 300ms ease";
      el.style.opacity = "0";
      el.style.transform = "translateY(-6px)";
      setTimeout(() => el.remove(), 350);
    }, 4500);
  });
}

// ---------------------------------------------------------- Confirmation dialogs

function initConfirms() {
  document.querySelectorAll("[data-confirm]").forEach((el) => {
    el.addEventListener("click", (ev) => {
      const msg = el.getAttribute("data-confirm");
      if (!window.confirm(msg)) ev.preventDefault();
    });
  });
}

// ---------------------------------------------------------- Keyboard shortcuts

function initKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Ignore when user is typing into a text field with a modifier we don't handle.
    const target = e.target;
    const inField = target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);

    // Cmd+S / Ctrl+S -> submit the primary form on the page.
    if ((e.metaKey || e.ctrlKey) && e.key === "s") {
      const form =
        document.getElementById("report-form") ||
        document.querySelector("form.card.stack") ||
        document.querySelector("main form");
      if (form) {
        e.preventDefault();
        form.requestSubmit ? form.requestSubmit() : form.submit();
      }
      return;
    }

    // '/' focus search (for future), Esc blur inputs.
    if (e.key === "Escape" && inField) {
      target.blur();
    }
  });
}

// ---------------------------------------------------------- Input polish

function initInputPolish() {
  // Auto-select numeric fields on focus so the user can overwrite immediately.
  document.querySelectorAll("input[type='number']").forEach((inp) => {
    inp.addEventListener("focus", () => inp.select());
  });

  // Restrict SSN / last4 fields to numeric on client side (server still validates).
  document.querySelectorAll("input[maxlength='4'][inputmode='numeric']").forEach((inp) => {
    inp.addEventListener("input", () => {
      inp.value = inp.value.replace(/\D/g, "").slice(0, 4);
    });
  });
}

// ---------------------------------------------------------- Boot

document.addEventListener("DOMContentLoaded", () => {
  initToasts();
  initConfirms();
  initKeyboardShortcuts();
  initInputPolish();
});
