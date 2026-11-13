"use strict";

// One page for the served hub (live, writable) and the static build (read-only).
const params = new URLSearchParams(location.hash.slice(1));
const token = params.get("token") || "";
const staticData = window.HUB_STATIC || null;
const grid = document.getElementById("grid");
const filter = document.getElementById("filter");
const connection = document.getElementById("connection");
const message = document.getElementById("message");
let items = [];

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("data-")) node.setAttribute(key, value);
    else node[key] = value;
  }
  for (const child of children) {
    if (child === null || child === undefined) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function fileUrl(file) {
  if (!file.url) return null;
  if (staticData) return staticData.file_base + encodeURI(file.path);
  return `${file.url}?token=${encodeURIComponent(token)}`;
}

function showMessage(text) {
  message.textContent = text;
  message.hidden = !text;
}

function setConnection(state) {
  connection.dataset.state = state;
  connection.textContent = state;
}

async function post(body) {
  const response = await fetch("api/events", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Hub-Token": token },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload.event;
}

async function decide(item, decision, note) {
  try {
    await post({
      type: "decision",
      asset: item.asset,
      decision,
      version_id: item.current_version,
      body: note || null,
    });
    showMessage("");
  } catch (error) {
    showMessage(`${item.title}: ${error.message}`);
  }
}

function preview(version) {
  const file = version && version.files.find((f) => (f.media_type || "").startsWith("image/"));
  const url = file && fileUrl(file);
  if (url) return el("img", { class: "preview", src: url, alt: file.path, loading: "lazy" });
  const first = version && version.files[0];
  return el("p", { class: "meta" }, first ? `${first.path} (no preview yet)` : "no version yet");
}

function actions(item) {
  if (staticData || !item.current_version) return null;
  const note = el("textarea", { placeholder: "Note for a retake or reject", "data-note": "1" });
  const button = (decision, label) => {
    const node = el("button", { type: "button", "data-action": decision }, label);
    node.addEventListener("click", () => decide(item, decision, note.value.trim()));
    return node;
  };
  return el("div", { class: "actions" },
    button("approve", "Approve (A)"), button("retake", "Retake (R)"), button("reject", "Reject"),
    note);
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

function card(item) {
  const current = item.versions.find((v) => v.id === item.current_version);
  const notes = item.events.filter((e) => e.body).slice(-3);
  const node = el("article", {
    class: "card", tabIndex: 0, "data-asset": item.asset, "data-status": item.status,
    "data-current": item.current_version || "",
  },
  el("h2", {}, item.title),
  el("div", { class: "meta" }, `${item.family} / ${item.kind}${item.ship ? " / ships" : ""} `,
    el("span", { class: `pill ${item.status}` }, item.status)),
  preview(current),
  actions(item),
  ...notes.map((e) => el("p", { class: "note" }, `${e.author}: ${e.body}`)),
  el("ul", { class: "versions" }, ...item.versions.map((v) => versionRow(item, v))));
  node.addEventListener("keydown", (event) => onKey(event, item, node));
  return node;
}

function onKey(event, item, node) {
  if (event.target.tagName === "TEXTAREA") return;
  const key = event.key.toLowerCase();
  if (key === "a" && !staticData) decide(item, "approve", "");
  else if (key === "r" && !staticData) node.querySelector("[data-note]").focus();
  else if (key === "j") (node.nextElementSibling || node).focus();
  else if (key === "k") (node.previousElementSibling || node).focus();
  else return;
  event.preventDefault();
}

function render() {
  // A live update must not lose a half-typed note or the reviewer's place.
  const typed = new Map();
  for (const note of grid.querySelectorAll("[data-note]")) {
    if (note.value) typed.set(note.closest(".card").dataset.asset, note.value);
  }
  const active = document.activeElement;
  const focusedCard = active && active.closest && active.closest(".card");
  const keep = focusedCard && focusedCard.dataset.asset;
  const inNote = active && active.matches && active.matches("[data-note]");
  const wanted = filter.value;
  grid.replaceChildren(...items.filter((i) => !wanted || i.status === wanted).map(card));
  for (const [asset, text] of typed) {
    const note = grid.querySelector(`[data-asset="${CSS.escape(asset)}"] [data-note]`);
    if (note) note.value = text;
  }
  const again = keep && grid.querySelector(`[data-asset="${CSS.escape(keep)}"]`);
  if (again) (inNote ? again.querySelector("[data-note]") || again : again).focus();
}

filter.value = params.get("status") || "";
filter.addEventListener("change", () => {
  params.set("status", filter.value);
  history.replaceState(null, "", `#${params}`);
  render();
});

if (staticData) {
  setConnection("read-only");
  items = staticData.items;
  render();
} else {
  const stream = new EventSource(`api/stream?token=${encodeURIComponent(token)}`);
  stream.addEventListener("items", (event) => {
    items = JSON.parse(event.data).items;
    setConnection("live");
    render();
  });
  stream.addEventListener("error", () => setConnection("offline"));
}
