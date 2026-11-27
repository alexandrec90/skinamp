"use strict";

const element = (id) => document.getElementById(id);
const state = { themes: [], busy: false, status: null };

// Not a theme Skinamp applies: choosing it undoes whatever theme is on.
const DEFAULT_CARD = {
  id: "default",
  name: "Default",
  description: "Your own desktop, exactly as it was before Skinamp changed anything.",
  preview: {},
  needs_admin: false,
};

const STATUS_TEXT = {
  default: ["Your own desktop", "Nothing is changed."],
  applying: ["Interrupted", "A theme was only partly applied. Choose Default to clean up."],
  reverting: ["Undo not finished", "Some changes could not be undone yet. Choose Default again."],
  unreadable: ["Undo record unreadable", ""],
};

function activeId() {
  const status = state.status;
  if (!status) return null;
  if (status.state === "default") return DEFAULT_CARD.id;
  if (status.state === "applied") return status.theme;
  // Part-applied or part-undone: nothing is fully on, so every card stays choosable.
  return null;
}

function card(theme) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "card";
  button.dataset.id = theme.id;
  const title = document.createElement("strong");
  title.textContent = theme.name;
  const preview = document.createElement("div");
  preview.className = "preview";
  preview.append(
    ...Object.entries(theme.preview).map(([name, source]) => {
      const image = document.createElement("img");
      image.src = source;
      image.alt = "";
      image.title = name;
      return image;
    }),
  );
  if (theme.id === DEFAULT_CARD.id) preview.classList.add("plain");
  const description = document.createElement("small");
  description.textContent = theme.description;
  button.append(title, preview, description);
  if (theme.needs_admin) {
    const badge = document.createElement("em");
    badge.className = "admin";
    badge.textContent = "Windows will ask for admin permission";
    button.append(badge);
  }
  button.addEventListener("click", () => choose(theme));
  return button;
}

function renderCards() {
  element("themes").replaceChildren(...[DEFAULT_CARD, ...state.themes].map(card));
}

function syncCards() {
  const active = activeId();
  for (const button of document.querySelectorAll(".card")) {
    const on = button.dataset.id === active;
    button.setAttribute("aria-pressed", String(on));
    button.disabled = state.busy || on;
  }
}

function showMessage(title, detail = "") {
  element("status-title").textContent = title;
  element("status-detail").textContent = detail;
}

function themeName(id) {
  return state.themes.find((theme) => theme.id === id)?.name ?? id;
}

function renderStatus(status) {
  state.status = status;
  const known = STATUS_TEXT[status.state];
  if (known) {
    showMessage(known[0], status.error || known[1]);
  } else {
    showMessage(`${themeName(status.theme)} is on`, `${status.changes} changes, all undoable.`);
  }
  syncCards();
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
  syncCards();
  showMessage(startMessage);
  try {
    return await action();
  } finally {
    state.busy = false;
    syncCards();
  }
}

async function applyTheme(theme) {
  const api = window.pywebview.api;
  const result = await run(`Switching to ${theme.name}…`, () => api.apply(theme.id));
  renderStatus(await api.get_status());
  if (result.ok) {
    showMessage(`${theme.name} is on`, describeApply(result));
  } else {
    const after = result.rolled_back ? "Everything was put back." : result.pending.join("\n");
    showMessage("That didn't work", `${result.error}\n${after}`);
  }
}

async function revertTheme() {
  const api = window.pywebview.api;
  const result = await run("Going back to your own desktop…", () => api.revert());
  renderStatus(await api.get_status());
  if (result.error) {
    showMessage("That didn't work", result.error);
  } else {
    showMessage(...describeRevert(result));
  }
}

function choose(theme) {
  return theme.id === DEFAULT_CARD.id ? revertTheme() : applyTheme(theme);
}

async function start() {
  const api = window.pywebview.api;
  const initial = await api.get_state();
  state.themes = initial.themes;
  element("version").textContent = `Skinamp ${initial.version}`;
  renderCards();
  renderStatus(initial.status);
  element("restart").addEventListener("click", () => api.restart_to_update());
  renderUpdate(await api.check_updates());
}

window.addEventListener("pywebviewready", start);
