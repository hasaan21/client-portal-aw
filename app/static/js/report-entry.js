/**
 * Live totals for the quarterly report entry page.
 *
 * Every keystroke on a balance / cash / stale-checkbox / liability-balance
 * field is debounced then posted (as form-encoded data) to the report's
 * live-totals endpoint. The response is a JSON object of Decimal-as-string
 * totals which we render back into the sticky footer.
 *
 * We keep the server as the single source of truth for math — this file only
 * mirrors it visually so users see the impact of their edits without waiting
 * for save.
 */

const DEBOUNCE_MS = 250;

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function formatMoney(str) {
  const n = Number(str);
  if (Number.isNaN(n)) return "$0.00";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

async function fetchTotals(form, endpoint) {
  const data = new FormData(form);
  const resp = await fetch(endpoint, {
    method: "POST",
    body: data,
    headers: { "X-Requested-With": "XMLHttpRequest" },
    credentials: "same-origin",
  });
  if (!resp.ok) return null;
  return resp.json();
}

function renderTotals(totals) {
  document.querySelectorAll("[data-total]").forEach((el) => {
    const key = el.dataset.total;
    if (key in totals) el.textContent = formatMoney(totals[key]);
  });
}

function wireUseLastValueChips() {
  document.querySelectorAll("[data-use-last-value]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const targetName = chip.dataset.target;
      const value = chip.dataset.value;
      const input = document.querySelector(`[name="${targetName}"]`);
      if (input) {
        input.value = value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.focus();
      }
    });
  });
}

function init() {
  const form = document.getElementById("report-form");
  const totalsBox = document.getElementById("live-totals");
  if (!form || !totalsBox) return;

  const endpoint = totalsBox.dataset.endpoint;
  const update = debounce(async () => {
    const totals = await fetchTotals(form, endpoint);
    if (totals) renderTotals(totals);
  }, DEBOUNCE_MS);

  form.addEventListener("input", update, { passive: true });
  form.addEventListener("change", update, { passive: true });
  wireUseLastValueChips();
}

document.addEventListener("DOMContentLoaded", init);
