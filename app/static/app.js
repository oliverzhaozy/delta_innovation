// Nav dropdowns: opening one closes the others; any outside tap closes all.
// (The <details> element does the real work — this is courtesy behavior only,
// so the nav still functions with JS disabled.)
document.addEventListener("click", (event) => {
  const inside = event.target.closest("details.navgroup");
  document.querySelectorAll("details.navgroup[open]").forEach((group) => {
    if (group !== inside) group.removeAttribute("open");
  });
});

// Copy-to-clipboard for generated text.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const source = document.querySelector(button.dataset.copy);
  if (!source) return;
  navigator.clipboard.writeText(source.innerText).then(() => {
    const original = button.textContent;
    button.textContent = "Copied ✓";
    setTimeout(() => (button.textContent = original), 1500);
  });
});

// Calendar layer toggles: each pill hides/shows its colour layer on the month
// grid, persisted in localStorage so the choice survives month navigation.
// Purely cosmetic — the server already omits ARCTIC chips for non-command users.
const CAL_FILTER_KEY = "delta.calFilters";

function readHiddenCals() {
  try {
    return new Set(JSON.parse(localStorage.getItem(CAL_FILTER_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function applyCalFilters(hidden) {
  const grid = document.querySelector(".month-grid");
  document.querySelectorAll("[data-cal-toggle]").forEach((button) => {
    const key = button.dataset.calToggle;
    const on = !hidden.has(key);
    button.setAttribute("aria-pressed", on ? "true" : "false");
    if (grid) grid.classList.toggle("hide-cal-" + key, !on);
  });
}

document.addEventListener("DOMContentLoaded", () => applyCalFilters(readHiddenCals()));

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-cal-toggle]");
  if (!button) return;
  const hidden = readHiddenCals();
  const key = button.dataset.calToggle;
  if (hidden.has(key)) hidden.delete(key);
  else hidden.add(key);
  localStorage.setItem(CAL_FILTER_KEY, JSON.stringify([...hidden]));
  applyCalFilters(hidden);
});
