"use strict";

const element = (id) => document.getElementById(id);
const state = { themes: [], busy: false, status: null };

const STATUS_TEXT = {
  default: ["Your own desktop", "Nothing is changed."],
  applying: ["Interrupted", "A theme was only partly applied. Undo to clean up."],
  reverting: ["Undo not finished", "Some changes could not be undone yet. Undo again."],
  unreadable: ["Undo record unreadable", ""],
};

function currentTheme() {
  return state.themes.find((theme) => theme.id === element("theme").value);
}

function selectedComponents() {
  return [...document.querySelectorAll("#components input:checked")].map((box) => box.value);
}

function renderTheme() {
  const theme = currentTheme();
  element("theme-description").textContent = theme.description;
  const preview = element("preview");
  preview.replaceChildren(
    ...Object.entries(theme.preview).map(([name, source]) => {
      const figure = document.createElement("figure");
      const image = document.createElement("img");
      image.src = source;
      image.alt = "";
      const caption = document.createElement("figcaption");
      caption.textContent = name;
      figure.append(image, caption);
      return figure;
    }),
  );
  const list = element("components");
  list.replaceChildren(
    ...theme.components.map((component) => {
      const label = document.createElement("label");
      label.className = "choice";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = component.id;
      box.checked = true;
      const text = document.createElement("span");
      const detail = document.createElement("small");
      text.textContent = component.title;
      detail.textContent = component.description;
      if (component.needs_admin) {
        const badge = document.createElement("em");
        badge.className = "admin";
        badge.textContent = "Windows will ask for admin permission";
        detail.append(" ", badge);
      }
      text.append(detail);
      label.append(box, text);
      return label;
    }),
  );
}

function showMessage(title, detail = "") {
  element("status-title").textContent = title;
  element("status-detail").textContent = detail;
}

function renderStatus(status) {
  state.status = status;
  const known = STATUS_TEXT[status.state];
  if (known) {
    showMessage(known[0], status.error || known[1]);
  } else {
    const parts = status.components.join(", ");
    showMessage(`${status.theme} theme is on`, `${status.changes} changes, all undoable: ${parts}`);
  }
  syncButtons();
}

function syncButtons() {
  const nothingToUndo = !state.status || state.status.state === "default";
  element("apply").disabled = state.busy;
  element("revert").disabled = state.busy || nothingToUndo;
}

function renderUpdate(update) {
  const ready = update.phase === "ready";
  element("update").hidden = !ready;
  if (ready) {
    element("update-text").textContent =
      `Version ${update.version} is ready. It installs when you close Skinamp.`;
  }
}

function describeApply(result) {
  const lines = [`${result.changes} changes made.`];
  for (const skipped of result.skipped) {
    lines.push(`Skipped ${skipped.component}: ${skipped.reason}`);
  }
  return lines.concat(result.warnings).join("\n");
}

function describeRevert(result) {
  if (result.pending.length > 0) {
    const reasons = [...new Set(result.pending)].join("\n");
    return ["Not finished", `Some changes are still in place:\n${reasons}`];
  }
  return ["Your own desktop is back", `${result.restored} changes undone.`];
}

async function run(startMessage, action) {
  state.busy = true;
  syncButtons();
  showMessage(startMessage);
  try {
    return await action();
  } finally {
    state.busy = false;
    syncButtons();
  }
}

async function applyTheme() {
  const api = window.pywebview.api;
  const theme = currentTheme();
  const result = await run("Applying…", () => api.apply(theme.id, selectedComponents()));
  renderStatus(await api.get_status());
  if (result.ok) {
    showMessage(`${theme.name} theme is on`, describeApply(result));
  } else {
    const after = result.rolled_back ? "Everything was put back." : result.pending.join("\n");
    showMessage("That didn't work", `${result.error}\n${after}`);
  }
}

async function revertTheme() {
  const api = window.pywebview.api;
  const result = await run("Undoing…", () => api.revert());
  renderStatus(await api.get_status());
  if (result.error) {
    showMessage("That didn't work", result.error);
  } else {
    showMessage(...describeRevert(result));
  }
}

async function start() {
  const api = window.pywebview.api;
  const initial = await api.get_state();
  state.themes = initial.themes;
  element("theme").replaceChildren(
    ...initial.themes.map((theme) => new Option(theme.name, theme.id)),
  );
  element("version").textContent = `Skinamp ${initial.version}`;
  renderTheme();
  renderStatus(initial.status);
  element("theme").addEventListener("change", renderTheme);
  element("apply").addEventListener("click", applyTheme);
  element("revert").addEventListener("click", revertTheme);
  element("restart").addEventListener("click", () => api.restart_to_update());
  renderUpdate(await api.check_updates());
}

window.addEventListener("pywebviewready", start);
