"use strict";

// One page for the served hub (live, writable) and the static build (read-only).
const { el } = window.HubDom;
const params = new URLSearchParams(location.hash.slice(1));
const token = params.get("token") || "";
const staticData = window.HUB_STATIC || null;
const grid = document.getElementById("grid");
const filter = document.getElementById("filter");
const connection = document.getElementById("connection");
const message = document.getElementById("message");
// A box drawn but not yet sent, per asset; it survives live re-renders.
const drafts = new Map();
let items = [];

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

async function post(item, body) {
  try {
    const response = await fetch("api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Hub-Token": token },
      body: JSON.stringify({ asset: item.asset, version_id: item.current_version, ...body }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    showMessage("");
    return payload.event;
  } catch (error) {
    showMessage(`${item.title}: ${error.message}`);
    return null;
  }
}

function decide(item, decision, note) {
  return post(item, { type: "decision", decision, body: note || null });
}

async function addNote(item, textarea) {
  const body = textarea.value.trim();
  if (!body) {
    showMessage(`${item.title}: write the note first`);
    return;
  }
  const region = drafts.get(item.asset) || null;
  if (await post(item, { type: "note", body, region })) {
    drafts.delete(item.asset);
    textarea.value = "";
  }
}

function regionNotes(item, versionId) {
  return item.events.filter((e) => e.type === "note" && e.region && e.version_id === versionId);
}

function viewerContext(item) {
  return {
    fileUrl,
    writable: !staticData,
    regionNotes: (versionId) => regionNotes(item, versionId),
    draft: () => drafts.get(item.asset) || null,
    setDraft: (region) => (region ? drafts.set(item.asset, region) : drafts.delete(item.asset)),
  };
}

function actions(item) {
  if (staticData || !item.current_version) return null;
  const note = el("textarea", {
    placeholder: "Note; drag on the picture to point at a spot", "data-note": "1",
  });
  const button = (action, label, run) => {
    const node = el("button", { type: "button", "data-action": action }, label);
    node.addEventListener("click", run);
    return node;
  };
  const decision = (name, label) => button(name, label, () => decide(item, name, note.value.trim()));
  return el("div", { class: "actions" },
    decision("approve", "Approve (A)"), decision("retake", "Retake (R)"),
    decision("reject", "Reject"), button("note", "Note (N)", () => addNote(item, note)), note);
}

function noteLine(item, event) {
  const numbered = event.region ? regionNotes(item, event.version_id) : [];
  const label = event.region ? `[${numbered.indexOf(event) + 1}] ` : "";
  const line = el("p", { class: "note", "data-event": event.id }, `${label}${event.author}: ${event.body}`);
  if (event.region) {
    line.addEventListener("click", () => {
      const card = line.closest(".card");
      for (const box of card.querySelectorAll(".region.active")) box.classList.remove("active");
      const box = card.querySelector(`.region[data-event="${CSS.escape(event.id)}"]`);
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

function card(item) {
  const current = item.versions.find((v) => v.id === item.current_version);
  const notes = item.events.filter((e) => e.body).slice(-5);
  const node = el("article", {
    class: "card", tabIndex: 0, "data-asset": item.asset, "data-status": item.status,
    "data-current": item.current_version || "", "data-kind": item.kind,
  },
  el("h2", {}, item.title),
  el("div", { class: "meta" }, `${item.family} / ${item.kind}${item.ship ? " / ships" : ""} `,
    el("span", { class: `pill ${item.status}` }, item.status)),
  window.HubViewers.view(item, current, viewerContext(item)),
  actions(item),
  ...notes.map((e) => noteLine(item, e)),
  el("ul", { class: "versions" }, ...item.versions.map((v) => versionRow(item, v))));
  node.addEventListener("keydown", (event) => onKey(event, item, node));
  return node;
}

function onKey(event, item, node) {
  if (["TEXTAREA", "INPUT", "SELECT"].includes(event.target.tagName)) return;
  const key = event.key.toLowerCase();
  if (key === "a" && !staticData) decide(item, "approve", "");
  else if ((key === "r" || key === "n") && !staticData) node.querySelector("[data-note]").focus();
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
