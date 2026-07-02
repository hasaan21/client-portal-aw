/**
 * Global site behavior. Kept intentionally tiny — feature-specific JS lives
 * next to the blueprint that owns it.
 */

const AUTO_DISMISS_MS = 6000;

function autoDismissFlashes() {
  document.querySelectorAll(".flash").forEach((el) => {
    setTimeout(() => {
      el.style.transition = "opacity 300ms ease, transform 300ms ease";
      el.style.opacity = "0";
      el.style.transform = "translateY(-4px)";
      setTimeout(() => el.remove(), 320);
    }, AUTO_DISMISS_MS);
  });
}

function wireConfirmButtons() {
  document.querySelectorAll("[data-confirm]").forEach((el) => {
    el.addEventListener("click", (ev) => {
      const message = el.dataset.confirm || "Are you sure?";
      if (!window.confirm(message)) {
        ev.preventDefault();
        ev.stopPropagation();
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  autoDismissFlashes();
  wireConfirmButtons();
});
