"use strict";

// The bulk bar: pick cards (shift extends a range), then approve, reject or retake them with
// one shared hint. Each asset still gets its own decision event, written by the same route.
window.HubBulk = (() => {
  const bar = document.getElementById("bulk");
  const selectShown = document.getElementById("select-shown");
  const shownCount = document.getElementById("shown-count");
  const selectedCount = document.getElementById("selected-count");
  const panel = document.getElementById("bulk-panel");
  const question = document.getElementById("bulk-question");
  const hint = document.getElementById("bulk-hint");
  const go = document.getElementById("bulk-go");
  const progress = document.getElementById("progress");
  // The status each decision leads to; a run skips assets already there.
  const REACHES = { approve: "approved", retake: "retake", reject: "rejected" };
  const selected = new Set();
  let context = null;
  let lastPicked = null;
  let decision = null;

  function has(asset) {
    return selected.has(asset);
  }

  function pick(asset, on, range) {
    const ids = context.visible().map((i) => i.asset);
    let chosen = [asset];
    const from = ids.indexOf(lastPicked);
    const to = ids.indexOf(asset);
    if (range && from >= 0 && to >= 0) chosen = ids.slice(Math.min(from, to), Math.max(from, to) + 1);
    for (const id of chosen) {
      if (on) selected.add(id);
      else selected.delete(id);
    }
    lastPicked = asset;
    sync();
  }

  // Drops picks of assets the registry no longer lists.
  function keepOnly(assets) {
    for (const asset of [...selected]) if (!assets.has(asset)) selected.delete(asset);
  }

  function sync() {
    if (!context) return;
    for (const [asset, node] of context.nodes()) {
      const on = selected.has(asset);
      node.classList.toggle("selected", on);
      const box = node.querySelector("[data-select]");
      if (box) box.checked = on;
    }
    const shown = context.visible();
    const picked = shown.filter((i) => selected.has(i.asset)).length;
    shownCount.textContent = `Select all ${shown.length} shown`;
    selectShown.checked = shown.length > 0 && picked === shown.length;
    selectShown.indeterminate = picked > 0 && picked < shown.length;
    selectedCount.textContent = `${selected.size} selected`;
    for (const node of bar.querySelectorAll("[data-bulk]")) {
      node.disabled = node.dataset.bulk !== "clear" && (selected.size === 0 || bar.dataset.busy === "1");
    }
  }

  function ask(chosen) {
    decision = chosen;
    const count = selected.size;
    const noun = `${count} selected asset${count === 1 ? "" : "s"}`;
    question.textContent = decision === "retake"
      ? `Retake ${noun}. The hint goes to each of them.`
      : `${decision === "approve" ? "Approve" : "Reject"} ${noun}?`;
    hint.hidden = decision !== "retake";
    go.textContent = `${decision[0].toUpperCase()}${decision.slice(1)} ${count}`;
    panel.hidden = false;
    (decision === "retake" ? hint : go).focus();
  }

  function close() {
    panel.hidden = true;
    decision = null;
  }

  async function run() {
    const chosenDecision = decision;
    const reason = chosenDecision === "retake" ? hint.value.trim() : "";
    close();
    const chosen = context.items().filter((i) => selected.has(i.asset));
    const skipped = chosen.filter((i) => i.status === REACHES[chosenDecision] || !i.current_version);
    for (const item of skipped) selected.delete(item.asset);
    const queue = chosen.filter((i) => !skipped.includes(i));
    const total = queue.length;
    const refused = [];
    let done = 0;
    bar.dataset.busy = "1";
    sync();
    // A few requests in flight hide the round trips; the server writes them one at a time.
    const worker = async () => {
      while (queue.length) {
        const item = queue.shift();
        try {
          await context.send(item, { type: "decision", decision: chosenDecision, body: reason || null });
          selected.delete(item.asset);
        } catch (error) {
          refused.push(`${item.title}: ${error.message}`);
        }
        done += 1;
        progress.textContent = `${chosenDecision} ${done} / ${total}`;
      }
    };
    await Promise.all([1, 2, 3, 4].map(worker));
    delete bar.dataset.busy;
    if (chosenDecision === "retake") hint.value = "";
    const already = skipped.length ? `, ${skipped.length} already ${REACHES[chosenDecision]}` : "";
    progress.textContent = `${chosenDecision}: ${total - refused.length} done${already}`;
    const more = refused.length > 3 ? "; …" : "";
    context.showMessage(refused.length
      ? `${refused.length} refused and still selected: ${refused.slice(0, 3).join("; ")}${more}`
      : "");
    sync();
  }

  // context: items(), visible(), nodes() as [asset, card] pairs, send(item, body), showMessage.
  function init(next) {
    context = next;
    bar.hidden = false;
    selectShown.addEventListener("change", () => {
      for (const item of context.visible()) {
        if (selectShown.checked) selected.add(item.asset);
        else selected.delete(item.asset);
      }
      sync();
    });
    for (const node of bar.querySelectorAll("[data-bulk]")) {
      node.addEventListener("click", () => {
        if (node.dataset.bulk !== "clear") {
          ask(node.dataset.bulk);
          return;
        }
        selected.clear();
        sync();
      });
    }
    go.addEventListener("click", run);
    document.getElementById("bulk-cancel").addEventListener("click", close);
    hint.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) run();
      else if (event.key === "Escape") close();
      else return;
      event.preventDefault();
    });
  }

  return { init, has, pick, keepOnly, sync };
})();
