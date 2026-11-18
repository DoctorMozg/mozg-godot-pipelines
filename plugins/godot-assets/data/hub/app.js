"use strict";

// One page for the served hub (live, writable) and the static build (read-only).
const { el } = window.HubDom;
const params = new URLSearchParams(location.hash.slice(1));
const token = params.get("token") || "";
const staticData = window.HUB_STATIC || null;
const writable = !staticData;
const grid = document.getElementById("grid");
const filter = document.getElementById("filter");
const family = document.getElementById("family");
const search = document.getElementById("search");
const connection = document.getElementById("connection");
const message = document.getElementById("message");
const bulk = window.HubBulk;

const FORMS = {
  retake: {
    field: "data-hint", send: "Send retake", action: "send-retake",
    placeholder: "What should change compared to this take? Leave empty to just draw it again.",
  },
  note: {
    field: "data-note", send: "Add note", action: "send-note",
    placeholder: "Note; drag on the picture to point at a spot",
  },
};

// Page state per asset that must outlive a live re-render.
const drafts = new Map();
const typed = new Map();
const opened = new Map();
const unfolded = new Set();
const cards = new Map();
let items = [];

function fileUrl(file) {
  if (!file.url) return null;
  if (staticData) return staticData.file_base + encodeURI(file.path);
  const join = file.url.includes("?") ? "&" : "?";
  return `${file.url}${join}token=${encodeURIComponent(token)}`;
}

function showMessage(text) {
  message.textContent = text;
  message.hidden = !text;
}

function setConnection(state) {
  connection.dataset.state = state;
  connection.textContent = state;
}

function button(action, label, run, tone = "", key = "") {
  const node = el("button", {
    type: "button", class: `btn ${tone}`.trim(), "data-action": action,
    title: key ? `${label} (${key})` : label,
  }, label);
  node.addEventListener("click", run);
  return node;
}

async function send(item, body) {
  const response = await fetch("api/events", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Hub-Token": token },
    body: JSON.stringify({ asset: item.asset, version_id: item.current_version, ...body }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload.event;
}

async function post(item, body) {
  try {
    const event = await send(item, body);
    showMessage("");
    return event;
  } catch (error) {
    showMessage(`${item.title}: ${error.message}`);
    return null;
  }
}

function forget(item, kind) {
  const state = { ...typed.get(item.asset) };
  delete state[kind];
  typed.set(item.asset, state);
}

async function decide(item, decision, reason) {
  if (!(await post(item, { type: "decision", decision, body: reason || null }))) return;
  if (decision === "retake") forget(item, "retake");
  if (opened.get(item.asset) === "retake") toggle(item, null);
}

async function addNote(item, body) {
  if (!body) {
    showMessage(`${item.title}: write the note first`);
    return;
  }
  const region = drafts.get(item.asset) || null;
  if (await post(item, { type: "note", body, region })) {
    drafts.delete(item.asset);
    forget(item, "note");
    toggle(item, null);
  }
}

// Opens one form of a card (retake hint or note) or closes both, without a re-render.
function toggle(item, kind) {
  if (kind) opened.set(item.asset, kind);
  else opened.delete(item.asset);
  const node = cards.get(item.asset)?.node;
  if (!node) return;
  for (const form of node.querySelectorAll("[data-form]")) {
    form.hidden = form.dataset.form !== kind;
    if (!form.hidden) form.querySelector("textarea").focus();
  }
  if (!kind) node.focus();
}

function form(item, kind) {
  const spec = FORMS[kind];
  const text = el("textarea", {
    rows: 2, placeholder: spec.placeholder, value: typed.get(item.asset)?.[kind] || "", [spec.field]: "1",
  });
  text.addEventListener("input", () => typed.set(item.asset, { ...typed.get(item.asset), [kind]: text.value }));
  const submit = () => (kind === "retake"
    ? decide(item, "retake", text.value.trim())
    : addNote(item, text.value.trim()));
  text.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) submit();
    else if (event.key === "Escape") toggle(item, null);
    else return;
    event.preventDefault();
  });
  return el("div", { class: `form ${kind}`, "data-form": kind, hidden: opened.get(item.asset) !== kind },
    text,
    el("div", { class: "row" },
      button(spec.action, spec.send, submit, "primary"),
      button("cancel", "Cancel", () => toggle(item, null)),
      el("span", { class: "meta" }, "Enter sends, Shift+Enter breaks the line, Esc closes")));
}

function regionNotes(item, versionId) {
  return item.events.filter((e) => e.type === "note" && e.region && e.version_id === versionId);
}

function viewerContext(item) {
  return {
    fileUrl,
    writable,
    regionNotes: (versionId) => regionNotes(item, versionId),
    draft: () => drafts.get(item.asset) || null,
    setDraft: (region) => {
      if (!region) {
        drafts.delete(item.asset);
        return;
      }
      drafts.set(item.asset, region);
      toggle(item, "note");
    },
  };
}

function actions(item) {
  if (!writable || !item.current_version) return null;
  return el("div", { class: "actions" },
    button("approve", "Approve", () => decide(item, "approve", ""), "approve", "A"),
    button("retake", "Retake…", () => toggle(item, "retake"), "retake", "R"),
    button("reject", "Reject", () => decide(item, "reject", ""), "reject"),
    button("note", "Note…", () => toggle(item, "note"), "", "N"));
}

function noteLine(item, event) {
  const numbered = event.region ? regionNotes(item, event.version_id) : [];
  const label = event.region ? `[${numbered.indexOf(event) + 1}] ` : "";
  const what = event.type === "decision" ? ` (${event.decision})` : "";
  const line = el("p", { class: "note", "data-event": event.id }, `${label}${event.author}${what}: ${event.body}`);
  if (event.region) {
    line.addEventListener("click", () => {
      const node = line.closest(".card");
      for (const box of node.querySelectorAll(".region.active")) box.classList.remove("active");
      const box = node.querySelector(`.region[data-event="${CSS.escape(event.id)}"]`);
      if (box) box.classList.add("active");
    });
  }
  return line;
}

function versionRow(item, version) {
  const decision = version.decision;
  return el("li", {
    class: version.id === item.current_version ? "current" : "",
    "data-version": version.id,
    "data-stale": version.stale ? "true" : "false",
  },
  el("code", {}, version.id.slice(-8)),
  el("span", {}, version.origin),
  decision ? el("span", { class: `pill ${decision.decision}` }, decision.decision) : null,
  version.stale ? el("span", { class: "pill stale" }, "stale") : null,
  version.pruned ? el("span", { class: "meta" }, "pruned") : null);
}

function versions(item) {
  const count = item.versions.length;
  const node = el("details", { class: "versions", open: unfolded.has(item.asset) },
    el("summary", {}, `${count} version${count === 1 ? "" : "s"}`),
    el("ul", {}, ...item.versions.map((v) => versionRow(item, v))));
  node.addEventListener("toggle", () => (node.open ? unfolded.add(item.asset) : unfolded.delete(item.asset)));
  return node;
}

function picker(item) {
  if (!writable) return null;
  const box = el("input", {
    type: "checkbox", checked: bulk.has(item.asset), "data-select": "1", "aria-label": `Select ${item.title}`,
  });
  box.addEventListener("click", (event) => bulk.pick(item.asset, box.checked, event.shiftKey));
  return box;
}

function card(item) {
  const current = item.versions.find((v) => v.id === item.current_version);
  const notes = item.events.filter((e) => e.body).slice(-3);
  const editable = writable && item.current_version;
  const node = el("article", {
    class: "card", tabIndex: 0, "data-asset": item.asset, "data-status": item.status,
    "data-current": item.current_version || "", "data-kind": item.kind,
  },
  el("header", {},
    picker(item),
    el("h2", { title: `${item.title} (${item.asset})` }, item.title),
    el("span", { class: `pill ${item.status}` }, item.status.replace("_", " "))),
  el("div", { class: "meta" }, `${item.family} / ${item.kind}${item.ship ? " / ships" : ""}`),
  window.HubViewers.view(item, current, viewerContext(item)),
  actions(item),
  editable ? form(item, "retake") : null,
  editable ? form(item, "note") : null,
  notes.length ? el("div", { class: "notes" }, ...notes.map((e) => noteLine(item, e))) : null,
  versions(item));
  node.addEventListener("keydown", (event) => onKey(event, item, node));
  return node;
}

function onKey(event, item, node) {
  if (["TEXTAREA", "INPUT", "SELECT"].includes(event.target.tagName)) return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const key = event.key.toLowerCase();
  if (writable && key === "a") {
    decide(item, "approve", "");
    // Approving from the keyboard walks on, so a run of good takes is one key each.
    (node.nextElementSibling || node).focus();
  } else if (writable && key === "r") toggle(item, "retake");
  else if (writable && key === "n") toggle(item, "note");
  else if (writable && (key === "x" || (key === " " && event.target === node))) {
    bulk.pick(item.asset, !bulk.has(item.asset), event.shiftKey);
  } else if (key === "j") (node.nextElementSibling || node).focus();
  else if (key === "k") (node.previousElementSibling || node).focus();
  else return;
  event.preventDefault();
}

function visible() {
  const status = filter.value;
  const wantedFamily = family.value;
  const words = search.value.trim().toLowerCase();
  return items.filter((i) => (!status || i.status === status) && (!wantedFamily || i.family === wantedFamily) &&
    (!words || `${i.title} ${i.asset} ${i.family}`.toLowerCase().includes(words)));
}

function swap(old, node) {
  const focused = old.contains(document.activeElement) ? document.activeElement : null;
  if (old.isConnected) old.replaceWith(node);
  if (!focused) return;
  const field = ["data-note", "data-hint"].find((name) => focused.hasAttribute(name));
  (field ? node.querySelector(`[${field}]`) : node).focus();
}

// Only the cards whose item changed are rebuilt; the rest keep their loaded pictures.
function render() {
  const fresh = new Map();
  for (const item of items) {
    const signature = JSON.stringify(item);
    const known = cards.get(item.asset);
    if (known && known.signature === signature) {
      fresh.set(item.asset, known);
      continue;
    }
    const node = card(item);
    if (known) swap(known.node, node);
    fresh.set(item.asset, { signature, node });
  }
  cards.clear();
  for (const [asset, entry] of fresh) cards.set(asset, entry);
  bulk.keepOnly(new Set(cards.keys()));
  place();
  options();
  bulk.sync();
}

function place() {
  const wanted = visible().map((i) => cards.get(i.asset).node);
  const now = grid.children;
  if (wanted.length === now.length && wanted.every((node, i) => node === now[i])) return;
  const active = document.activeElement;
  grid.replaceChildren(...wanted);
  if (active && active !== document.body && active.isConnected) active.focus({ preventScroll: true });
}

// Filter choices carry their counts, so the bar doubles as the review's progress.
function options() {
  const tally = (key) => items.reduce((all, i) => all.set(i[key], (all.get(i[key]) || 0) + 1), new Map());
  const statuses = tally("status");
  for (const option of filter.options) {
    const count = option.value ? statuses.get(option.value) || 0 : items.length;
    option.textContent = `${option.value || "all"} (${count})`;
  }
  const families = tally("family");
  const chosen = family.value || params.get("family") || "";
  family.replaceChildren(el("option", { value: "" }, `all (${items.length})`),
    ...[...families.keys()].sort().map((name) => el("option", { value: name }, `${name} (${families.get(name)})`)));
  family.value = families.has(chosen) ? chosen : "";
}

function remember(key, value) {
  if (value) params.set(key, value);
  else params.delete(key);
  history.replaceState(null, "", `#${params}`);
}

filter.value = params.get("status") || "";
search.value = params.get("q") || "";
for (const [control, key] of [[filter, "status"], [family, "family"], [search, "q"]]) {
  control.addEventListener(control === search ? "input" : "change", () => {
    remember(key, control.value);
    place();
    bulk.sync();
  });
}

const stringContext = { token, readOnly: Boolean(staticData), fileUrl, showMessage };

if (staticData) {
  setConnection("read-only");
  items = staticData.items;
  render();
  window.HubStrings.render(staticData.strings, stringContext);
  window.HubFindings.render(staticData.findings, stringContext);
} else {
  bulk.init({
    items: () => items,
    visible,
    nodes: () => [...cards].map(([asset, entry]) => [asset, entry.node]),
    send,
    showMessage,
  });
  const stream = new EventSource(`api/stream?token=${encodeURIComponent(token)}`);
  stream.addEventListener("items", (event) => {
    const snapshot = JSON.parse(event.data);
    items = snapshot.items;
    setConnection("live");
    render();
    window.HubStrings.render(snapshot.strings, stringContext);
    window.HubFindings.render(snapshot.findings, stringContext);
  });
  stream.addEventListener("error", () => setConnection("offline"));
}
