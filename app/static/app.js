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

// Event form (UI-9): show only labels belonging to the selected calendar, and
// de-emphasise the time inputs when the event is all-day. Progressive
// enhancement only — the server validates the label↔calendar pairing and
// normalises all-day times regardless, so no-JS still works.
function initEventForm() {
  const cal = document.getElementById("calendar");
  const label = document.getElementById("label");
  if (cal && label) {
    const form = label.closest("form");
    let map = {};
    try {
      map = JSON.parse((form && form.dataset.labelCalendars) || "{}");
    } catch {
      map = {};
    }
    const syncLabels = () => {
      [...label.options].forEach((opt) => {
        const owner = map[opt.value]; // undefined for the "" (no label) option
        const ok = !owner || owner === cal.value;
        opt.hidden = !ok;
        opt.disabled = !ok;
      });
      const selected = label.options[label.selectedIndex];
      if (selected && selected.disabled) label.value = "";
    };
    cal.addEventListener("change", syncLabels);
    syncLabels();
  }

  const allDay = document.getElementById("all_day");
  if (allDay) {
    const timed = [document.getElementById("start_dt"), document.getElementById("end_dt")];
    const syncAllDay = () => {
      timed.forEach((el) => el && el.classList.toggle("time-muted", allDay.checked));
    };
    allDay.addEventListener("change", syncAllDay);
    syncAllDay();
  }

  // Participant picker (UI-11): a person appears in both their service and
  // platoon dropdown, so keep same-value people checkboxes in sync; show a live
  // "n selected" count per group; and stop a summary checkbox's click from also
  // toggling its <details>. All pure enhancement — the server dedupes duplicate
  // ids, so a no-JS user ticking the same person in two groups still saves one
  // row.
  const picker = document.querySelector("form[data-label-calendars]");
  if (picker) {
    const peopleBoxes = [...picker.querySelectorAll('input[name="people"]')];

    const refreshCount = (details) => {
      const badge = details.querySelector("summary [data-count]");
      if (!badge) return;
      const n = details.querySelectorAll('.picker-body input[name="people"]:checked').length;
      badge.textContent = n ? n + " selected" : "";
    };
    const refreshAll = () =>
      picker.querySelectorAll("details.picker").forEach(refreshCount);

    peopleBoxes.forEach((box) => {
      box.addEventListener("change", () => {
        peopleBoxes.forEach((other) => {
          if (other !== box && other.value === box.value) other.checked = box.checked;
        });
        refreshAll();
      });
    });

    picker.querySelectorAll('details.picker > summary > input[type="checkbox"]').forEach((box) => {
      box.addEventListener("click", (event) => event.stopPropagation());
    });

    refreshAll();
  }
}

document.addEventListener("DOMContentLoaded", initEventForm);
