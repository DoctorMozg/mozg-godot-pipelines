"use strict";

// The findings section: what godotkit's playtest oracles found, with the evidence and the
// replay's verdict, and the owner's approve (fix it), reject (not a problem) or retake (run again).
window.HubFindings = (() => {
  const { el } = window.HubDom;
  const section = document.getElementById("findings");
  const table = document.getElementById("finding-rows");
  const statusFilter = document.getElementById("finding-status");
  let rows = [];
  let context = null;

  async function decide(row, decision) {
    try {
      const response = await fetch("api/events", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Hub-Token": context.token },
        body: JSON.stringify({ type: "decision", item: row.id, decision }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      context.showMessage("");
    } catch (error) {
      context.showMessage(`${row.id}: ${error.message}`);
    }
  }

  function evidence(row) {
    const found = row.evidence || {};
    const parts = [];
    if (found.log_excerpt) parts.push(el("pre", { class: "meta" }, found.log_excerpt));
    if (found.node_path) parts.push(el("code", {}, found.node_path));
    if (found.state) parts.push(el("pre", { class: "meta" }, JSON.stringify(found.state)));
    if (found.screenshot) {
      const url = context.fileUrl({ url: `files/${encodeURI(found.screenshot)}`, path: found.screenshot });
      parts.push(el("a", { href: url, target: "_blank", rel: "noopener" },
        el("img", { src: url, alt: found.screenshot, loading: "lazy", class: "shot" })));
    }
    return parts;
  }

  function actions(row) {
    if (context.readOnly) return null;
    const button = (decision, label) => {
      const node = el("button", { type: "button", "data-decision": decision }, label);
      node.addEventListener("click", () => decide(row, decision));
      return node;
    };
    return el("div", { class: "actions" },
      button("approve", "Fix"), button("reject", "Not a problem"), button("retake", "Run again"));
  }

  function line(row) {
    const repro = row.repro || {};
    const runs = `${row.occurrences} run${row.occurrences === 1 ? "" : "s"}, step ${repro.step}, frame ${repro.frame}`;
    const reason = row.decision && row.decision.body;
    return el("tr", { "data-item": row.id, "data-status": row.status },
      el("td", {}, el("strong", {}, row.title),
        el("div", { class: "meta" }, `${row.scenario_id} · ${row.persona} · seed ${row.seed} · ${row.build}`)),
      el("td", {}, el("div", {}, `expected: ${row.expected}`), el("div", {}, `actual: ${row.actual}`),
        ...evidence(row)),
      el("td", {}, el("span", { class: `pill ${row.class}` }, row.class),
        el("div", { class: "meta" }, `${row.severity_suggested} · ${row.confidence}`),
        el("div", { class: "meta" }, runs), el("code", { class: "meta" }, repro.actions)),
      el("td", {}, el("span", { class: `pill ${row.status}` }, row.status),
        reason ? el("p", { class: "note" }, reason) : null),
      el("td", {}, actions(row)));
  }

  function draw() {
    const status = statusFilter.value;
    table.replaceChildren(...rows.filter((r) => !status || r.status === status).map(line));
  }

  function render(next, ctx) {
    rows = next || [];
    context = ctx;
    section.hidden = rows.length === 0;
    draw();
  }

  statusFilter.addEventListener("change", draw);
  return { render };
})();
