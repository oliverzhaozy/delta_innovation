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

// In-place assignment selects (duty grid cells, TU manning slot rows). Delegated
// so one listener covers a whole month grid's worth of cells. The client
// validates NOTHING — the server owns eligibility, the availability warning and
// its confirm card, and re-renders the truth either way; this only saves the
// click on the button beside the select. That button is the no-JS path, so it
// is hidden here rather than in CSS: no script, no hiding.
document.addEventListener("change", (event) => {
  const select = event.target.closest("select[data-autosubmit]");
  if (!select || !select.value) return;
  const form = select.closest("form");
  if (form) form.submit();
});

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-autosubmit-fallback]").forEach((button) => {
    button.hidden = true;
  });
});

// In-message drag recategorization (P10.5). Delegated so it works on all three
// parade pages. The client does NO count math: a drop only fills the hidden
// #override-form (person id + target category) and submits it — the server
// re-renders the whole document and the rebalanced numbers come back in the
// response, which is the only source of truth. HTML5 drag is desktop-only by
// design (decision D8): there is no touch fallback.
let draggedLine = null;

function dragSheet() {
  return document.getElementById("sheet-live");
}

function dragConfirm() {
  return document.getElementById("drag-confirm");
}

function submitOverride() {
  const form = document.getElementById("override-form");
  if (form) form.submit();
}

function closeDragConfirm() {
  const modal = dragConfirm();
  if (modal) modal.hidden = true;
}

document.addEventListener("dragstart", (event) => {
  const line = event.target.closest("[data-drag-person]");
  if (!line) return;
  draggedLine = line;
  event.dataTransfer.setData("text/plain", line.dataset.dragPerson);
  event.dataTransfer.effectAllowed = "move";
  const sheet = dragSheet();
  if (sheet) sheet.classList.add("drag-active");
});

document.addEventListener("dragend", () => {
  const sheet = dragSheet();
  if (sheet) sheet.classList.remove("drag-active");
  document.querySelectorAll(".drop-hover").forEach((zone) => {
    zone.classList.remove("drop-hover");
  });
});

document.addEventListener("dragover", (event) => {
  const zone = event.target.closest(".drop-zone");
  if (!zone) return;
  event.preventDefault(); // a droppable target must cancel dragover
  zone.classList.add("drop-hover");
});

document.addEventListener("dragleave", (event) => {
  const zone = event.target.closest(".drop-zone");
  if (!zone) return;
  // Ignore leaves into a child of the same zone; only clear when truly out.
  if (!zone.contains(event.relatedTarget)) zone.classList.remove("drop-hover");
});

document.addEventListener("drop", (event) => {
  const zone = event.target.closest(".drop-zone");
  if (!zone) return;
  event.preventDefault();
  zone.classList.remove("drop-hover");
  const personId = event.dataTransfer.getData("text/plain");
  const form = document.getElementById("override-form");
  if (!personId || !form) return;
  form.querySelector('input[name="person_id"]').value = personId;
  form.querySelector('input[name="target"]').value = zone.dataset.dropCategory;
  // A person whose line rests on keyed data (leave, MC, a course, a partial, an
  // in-camp remark) asks before moving; a plain present/stay-out line does not.
  const conflict = draggedLine ? draggedLine.dataset.conflict : "";
  const modal = dragConfirm();
  if (!conflict || !modal) {
    submitOverride();
    return;
  }
  modal.querySelector("[data-confirm-message]").textContent =
    conflict + " Move to " + zone.dataset.dropTitle + " anyway?";
  modal.hidden = false;
  const ok = modal.querySelector("[data-confirm-ok]");
  if (ok) ok.focus();
});

document.addEventListener("click", (event) => {
  const modal = dragConfirm();
  if (!modal || modal.hidden) return;
  if (event.target.closest("[data-confirm-ok]")) {
    submitOverride();
    return;
  }
  // Cancel, or a click on the backdrop itself (never on the dialog inside it).
  if (event.target.closest("[data-confirm-cancel]") || event.target === modal) {
    closeDragConfirm();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDragConfirm();
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
    // across the swap. Capture the value BEFORE changing type and restore it
    // after — a type change (or writing a value in the other type's format)
    // runs the browser's sanitizer, which silently empties the field.
    const syncAllDay = () => {
      timed.forEach((el) => {
        if (allDay.checked) {
          if (el.type !== "date") {
            const kept = el.value.slice(0, 10);
            el.type = "date";
            el.value = kept;
          }
        } else if (el.type !== "datetime-local") {
          const kept = el.value;
          el.type = "datetime-local";
          el.value = kept.length === 10 ? kept + "T08:00" : kept;
        }
      });
    };
    allDay.addEventListener("change", syncAllDay);
    syncAllDay();
  }

  // People picker (UI-11, shared since UI-19 by the calendar event form and the
  // parade FP bulk-add): keep each category checkbox and its dropdown in sync
  // both ways — ticking a group (NSF/REGULAR/PLATOON_x) ticks every member,
  // and a group whose members are all ticked ticks itself. A person shown in
  // both their service and platoon group stays consistent across the two, and
  // each group carries a live "n selected" count. All pure enhancement — the
  // server dedupes duplicate ids and unions category + person rows, so a no-JS
  // user still saves a coherent selection.
  const picker = document.querySelector("form[data-people-picker]");
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
