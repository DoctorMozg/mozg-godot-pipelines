"use strict";

// The strings section: each translation beside its source, notes and screenshots, with the
// owner's approve and retake. l10nkit reads the decisions back as the reviewed state.
window.HubStrings = (() => {
  const { el } = window.HubDom;
  const section = document.getElementById("strings");
  const table = document.getElementById("string-rows");
  const localeFilter = document.getElementById("string-locale");
  const stateFilter = document.getElementById("string-state");
  let rows = [];
  let context = null;
  // Retake hints being typed, by item; an open form survives the live re-render.
  const hints = new Map();

  async function decide(row, decision, body = null) {
    try {
      const response = await fetch("api/events", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Hub-Token": context.token },
        body: JSON.stringify({ type: "decision", item: row.item, decision, body }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      context.showMessage("");
      if (decision === "retake") close(row);
    } catch (error) {
      context.showMessage(`${row.item}: ${error.message}`);
    }
  }

  function text(value) {
    return Array.isArray(value) ? value.join(" | ") : value || "";
  }

  function shots(row) {
    // Pictures of this locale as Godot drew it come first; the source's own screenshots follow.
    const drawn = (row.locale_shots || []).map((path) => [path, "locale"]);
    const named = (row.screenshots || []).map((path) => [path, "source"]);
    return [...drawn, ...named].map(([path, kind]) => {
      const url = context.fileUrl({ url: `files/${encodeURI(path)}`, path });
      return el("a", { href: url, target: "_blank", rel: "noopener" },
        el("img", { src: url, alt: path, loading: "lazy", class: "shot", "data-kind": kind }));
    });
  }

  function actions(row) {
    // A stale text is not what Godot shows, so there is nothing to approve until it is redone.
    if (context.readOnly || row.state === "stale") return null;
    if (hints.has(row.item)) {
      return window.HubDom.inlineForm({
        kind: "retake", field: "data-hint", send: "Send retake", action: "send-retake",
        placeholder: "What should change in the translation? Leave empty to just translate it again.",
        value: hints.get(row.item),
        onInput: (text) => hints.set(row.item, text),
        submit: (text) => decide(row, "retake", text || null),
        cancel: () => close(row),
      });
    }
    const button = (decision, label, run) => {
      const node = el("button", { type: "button", class: `btn ${decision}`, "data-decision": decision }, label);
      node.addEventListener("click", run);
      return node;
    };
    return el("div", { class: "actions" },
      row.state === "reviewed" ? null : button("approve", "Approve", () => decide(row, "approve")),
      button("retake", "Retake…", () => open(row)));
  }

  function open(row) {
    hints.set(row.item, "");
    draw();
    table.querySelector(`[data-item="${CSS.escape(row.item)}"] [data-hint]`)?.focus();
  }

  function close(row) {
    hints.delete(row.item);
    draw();
  }

  function line(row) {
    const about = [row.context && `context: ${row.context}`, row.note,
      row.max_chars && `max ${row.max_chars} chars`].filter(Boolean).join(" · ");
    return el("tr", { "data-item": row.item, "data-state": row.state },
      el("td", {}, el("code", {}, row.key), el("div", { class: "meta" }, about)),
      el("td", {}, text(row.source_forms || row.source)),
      el("td", { lang: row.locale.replace("_", "-") }, text(row.forms || row.text),
        ...(row.notes || []).map((n) => el("p", { class: "note" }, `${n.author}: ${n.body}`))),
      el("td", {}, el("span", { class: `pill ${row.state}` }, row.state),
        el("div", { class: "meta" }, row.by && (row.by.model || row.by.kind))),
      el("td", {}, ...shots(row)),
      el("td", {}, actions(row)));
  }

  function draw() {
    const locale = localeFilter.value;
    const state = stateFilter.value;
    const shown = rows.filter((r) => (!locale || r.locale === locale) && (!state || r.state === state));
    table.replaceChildren(...shown.map(line));
  }

  function render(next, ctx) {
    rows = next || [];
    context = ctx;
    section.hidden = rows.length === 0;
    const locales = [...new Set(rows.map((r) => r.locale))].sort();
    const chosen = localeFilter.value;
    localeFilter.replaceChildren(el("option", { value: "" }, "all"),
      ...locales.map((l) => el("option", {}, l)));
    localeFilter.value = locales.includes(chosen) ? chosen : "";
    draw();
  }

  localeFilter.addEventListener("change", draw);
  stateFilter.addEventListener("change", draw);
  return { render };
})();
