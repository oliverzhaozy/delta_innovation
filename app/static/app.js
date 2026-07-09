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
    const timed = [document.getElementById("start_dt"), document.getElementById("end_dt")].filter(
      Boolean
    );
    // All-day events own dates only, so drop the time control entirely rather
    // than just de-emphasising it: swap each input to type="date" (the form
    // accepts the resulting date-only value) and back to datetime-local for a
    // timed event, trimming/padding the value so the field stays populated
    // across the swap.
    const syncAllDay = () => {
      timed.forEach((el) => {
        if (allDay.checked) {
          if (el.type !== "date") {
            if (el.value) el.value = el.value.slice(0, 10);
            el.type = "date";
          }
        } else if (el.type !== "datetime-local") {
          el.type = "datetime-local";
          if (el.value.length === 10) el.value = el.value + "T08:00";
        }
      });
    };
    allDay.addEventListener("change", syncAllDay);
    syncAllDay();
  }

  // Participant picker (UI-11): keep each category checkbox and its dropdown in
  // sync both ways — ticking a group (NSF/REGULAR/PLATOON_x) ticks every member,
  // and a group whose members are all ticked ticks itself. A person shown in
  // both their service and platoon group stays consistent across the two, and
  // each group carries a live "n selected" count. All pure enhancement — the
  // server dedupes duplicate ids and unions category + person rows, so a no-JS
  // user still saves a coherent selection.
  const picker = document.querySelector("form[data-label-calendars]");
  if (picker) {
    const peopleBoxes = [...picker.querySelectorAll('input[name="people"]')];
    const groups = [...picker.querySelectorAll("details.picker")].map((details) => ({
      details,
      cat: details.querySelector('summary > input[type="checkbox"]'),
      members: [...details.querySelectorAll('.picker-body input[name="people"]')],
    }));

    // One representative box per person id (a person shown in two groups shares
    // an id; the checked state is mirrored across duplicates, so any one speaks
    // for all). ALL covers every id; Command team covers the data-command ids.
    const boxByValue = new Map();
    peopleBoxes.forEach((box) => {
      if (!boxByValue.has(box.value)) boxByValue.set(box.value, box);
    });
    const allValues = [...boxByValue.keys()];
    const commandValues = [
      ...new Set(peopleBoxes.filter((box) => box.dataset.command).map((box) => box.value)),
    ];
    const allBox = document.getElementById("cat_all");
    const commandBox = document.getElementById("cat_command");

    // A person can appear in two groups; mirror any tick to every same-id box.
    const mirror = (value, checked) => {
      peopleBoxes.forEach((box) => {
        if (box.value === value) box.checked = checked;
      });
    };
    const everyChecked = (values) =>
      values.length > 0 && values.every((v) => boxByValue.get(v).checked);

    const refreshGroup = (group) => {
      // Category reflects "all members ticked"; the badge shows the live count.
      if (group.cat) {
        group.cat.checked = group.members.length > 0 && group.members.every((b) => b.checked);
      }
      const badge = group.details.querySelector("summary [data-count]");
      if (badge) {
        const n = group.members.filter((b) => b.checked).length;
        badge.textContent = n ? n + " selected" : "";
      }
    };
    const refreshAll = () => {
      groups.forEach(refreshGroup);
      // ALL and Command team reflect coverage of their whole set — ticked once
      // every id they stand for is ticked (whichever group the tick came from).
      if (allBox) allBox.checked = everyChecked(allValues);
      if (commandBox) commandBox.checked = everyChecked(commandValues);
    };

    // A covering box (ALL, Command team, or a group) drives its member set.
    const driveMembers = (box, values) => {
      values.forEach((v) => mirror(v, box.checked));
      refreshAll();
    };

    peopleBoxes.forEach((box) => {
      box.addEventListener("change", () => {
        mirror(box.value, box.checked);
        refreshAll();
      });
    });

    groups.forEach((group) => {
      if (!group.cat) return;
      // Ticking/clearing the group drives every member (and its duplicates).
      group.cat.addEventListener("change", () =>
        driveMembers(group.cat, group.members.map((b) => b.value))
      );
      // Keep the summary checkbox from also toggling the <details> open state.
      group.cat.addEventListener("click", (event) => event.stopPropagation());
    });
    if (allBox) allBox.addEventListener("change", () => driveMembers(allBox, allValues));
    if (commandBox) {
      commandBox.addEventListener("change", () => driveMembers(commandBox, commandValues));
    }

    // Initial reconciliation runs in the safe direction only: a server-checked
    // ALL / Command team / group (e.g. a pre-existing live category with no
    // person rows) ticks its members so the two agree, and refreshAll never
    // *clears* such a box because its members are now ticked too.
    if (allBox && allBox.checked) allValues.forEach((v) => mirror(v, true));
    if (commandBox && commandBox.checked) commandValues.forEach((v) => mirror(v, true));
    groups.forEach((group) => {
      if (group.cat && group.cat.checked) {
        group.members.forEach((box) => mirror(box.value, true));
      }
    });
    refreshAll();
  }
}

document.addEventListener("DOMContentLoaded", initEventForm);
