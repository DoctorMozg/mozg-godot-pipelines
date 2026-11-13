"use strict";

// DOM helper and the viewers, one per asset kind. Each viewer returns a node for one version.
window.HubDom = {
  el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key.startsWith("data-") || key.startsWith("aria-")) node.setAttribute(key, value);
      else node[key] = value;
    }
    for (const child of children) {
      if (child === null || child === undefined) continue;
      node.append(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  },
};

window.HubViewers = (() => {
  const { el } = window.HubDom;
  const BOX = /^xywh=percent:([\d.]+),([\d.]+),([\d.]+),([\d.]+)$/;

  function firstOf(version, prefix) {
    const files = version.files.filter((f) => (f.media_type || "").startsWith(prefix));
    return files.find((f) => f.role === "main") || files[0] || null;
  }

  function placeholder(version, why) {
    const first = version && version.files[0];
    return el("p", { class: "meta" }, first ? `${first.path} (${why})` : "no version yet");
  }

  function place(box, selector) {
    const match = BOX.exec(selector);
    if (!match) return false;
    const [x, y, w, h] = match.slice(1).map(Number);
    // CSSOM writes are allowed under the page's CSP; style attributes are not.
    Object.assign(box.style, { left: `${x}%`, top: `${y}%`, width: `${w}%`, height: `${h}%` });
    return true;
  }

  function percent(value, size) {
    return Math.min(100, Math.max(0, Math.round((value / size) * 10000) / 100));
  }

  // Dragging on the stage proposes a box; the card turns it into a note.
  function drawable(stage, layer, file, ctx) {
    let start = null;
    let draft = null;
    stage.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const rect = stage.getBoundingClientRect();
      start = { x: event.clientX - rect.left, y: event.clientY - rect.top, rect };
      for (const old of layer.querySelectorAll(".region.draft")) old.remove();
      draft = el("div", { class: "region draft" });
      layer.append(draft);
      stage.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    stage.addEventListener("pointermove", (event) => {
      if (!start) return;
      const { rect } = start;
      const x = Math.min(start.x, event.clientX - rect.left);
      const y = Math.min(start.y, event.clientY - rect.top);
      const w = Math.abs(event.clientX - rect.left - start.x);
      const h = Math.abs(event.clientY - rect.top - start.y);
      const selector = `xywh=percent:${percent(x, rect.width)},${percent(y, rect.height)},` +
        `${percent(w, rect.width)},${percent(h, rect.height)}`;
      place(draft, selector);
      draft.dataset.selector = selector;
    });
    stage.addEventListener("pointerup", () => {
      if (!start) return;
      start = null;
      const selector = draft && draft.dataset.selector;
      const [, , , w, h] = BOX.exec(selector || "") || [];
      if (selector && Number(w) > 0 && Number(h) > 0) {
        ctx.setDraft({ selector, file: file.role });
      } else {
        draft.remove();
        ctx.setDraft(null);
      }
    });
  }

  function image(item, version, ctx) {
    const file = version && firstOf(version, "image/");
    const url = file && ctx.fileUrl(file);
    if (!url) return placeholder(version, "no preview");
    const img = el("img", { class: "picture", src: url, alt: file.path, draggable: false });
    const layer = el("div", { class: "regions" });
    const stage = el("div", { class: "stage", "data-file": file.role }, img, layer);
    ctx.regionNotes(version.id).forEach((note, index) => {
      if (note.region.file && note.region.file !== file.role) return;
      const box = el("div", { class: "region", "data-event": note.id }, el("span", {}, `${index + 1}`));
      if (place(box, note.region.selector)) layer.append(box);
    });
    const pending = ctx.draft();
    if (pending) {
      const box = el("div", { class: "region draft", "data-selector": pending.selector });
      if (place(box, pending.selector)) layer.append(box);
    }
    if (ctx.writable && version.id === item.current_version) drawable(stage, layer, file, ctx);
    return stage;
  }

  const byKind = {};

  function view(item, version, ctx) {
    if (!version) return placeholder(null, "");
    const viewer = byKind[item.kind] || image;
    return viewer(item, version, ctx);
  }

  return { view, byKind, firstOf, placeholder };
})();
