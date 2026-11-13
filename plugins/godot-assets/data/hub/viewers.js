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
  const TIME = /^t=([\d.]+)/;
  // Viewer state that must outlive a live re-render: chosen tab, sprite frame, playback.
  const memory = new Map();

  function remember(item, defaults) {
    if (!memory.has(item.asset)) memory.set(item.asset, { ...defaults });
    return memory.get(item.asset);
  }

  function imagesOf(version) {
    return version.files.filter((f) => (f.media_type || "").startsWith("image/"));
  }

  function firstOf(version, prefix) {
    const files = version.files.filter((f) => (f.media_type || "").startsWith(prefix));
    return files.find((f) => f.role === "main") || files[0] || null;
  }

  function placeholder(version, why) {
    const first = version && version.files[0];
    return el("p", { class: "meta" }, first ? `${first.path} (${why})` : "no version yet");
  }

  function button(label, action, run) {
    const node = el("button", { type: "button", "data-control": action }, label);
    node.addEventListener("click", run);
    return node;
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

  // Region notes on one file (and frame), numbered in the order the card lists them.
  function drawRegions(layer, item, version, ctx, where) {
    for (const old of layer.querySelectorAll(".region:not(.draft)")) old.remove();
    ctx.regionNotes(version.id).forEach((note, index) => {
      const { file, frame } = note.region;
      if (file && file !== where.file) return;
      if (where.frame !== undefined && frame !== undefined && frame !== where.frame) return;
      const box = el("div", { class: "region", "data-event": note.id }, el("span", {}, `${index + 1}`));
      if (place(box, note.region.selector)) layer.append(box);
    });
  }

  // Dragging on the stage proposes a box; the card turns it into a note.
  function drawable(stage, layer, ctx, where) {
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
        const region = { selector, file: where.file };
        if (where.frame !== undefined) region.frame = where.frame;
        ctx.setDraft(region);
      } else {
        draft.remove();
        ctx.setDraft(null);
      }
    });
  }

  function showDraft(layer, ctx) {
    const pending = ctx.draft();
    if (!pending) return;
    const box = el("div", { class: "region draft", "data-selector": pending.selector });
    if (place(box, pending.selector)) layer.append(box);
  }

  function image(item, version, ctx, chosen) {
    const file = chosen || firstOf(version, "image/");
    const url = file && ctx.fileUrl(file);
    if (!url) return placeholder(version, "no preview");
    const img = el("img", { class: "picture", src: url, alt: file.path, draggable: false });
    const layer = el("div", { class: "regions" });
    const stage = el("div", { class: "stage", "data-file": file.role }, img, layer);
    drawRegions(layer, item, version, ctx, { file: file.role });
    showDraft(layer, ctx);
    if (ctx.writable && version.id === item.current_version) drawable(stage, layer, ctx, { file: file.role });
    return stage;
  }

  // UI captures: one image per resolution, chosen by tab.
  function ui(item, version, ctx) {
    const shots = imagesOf(version);
    if (shots.length < 2) return image(item, version, ctx);
    const state = remember(item, { tab: shots[0].role });
    const chosen = shots.find((f) => f.role === state.tab) || shots[0];
    const tabs = el("div", { class: "tabs", role: "tablist" }, ...shots.map((file) => {
      const tab = button(file.role, "tab", () => {
        state.tab = file.role;
        node.replaceWith(ui(item, version, ctx));
      });
      tab.setAttribute("aria-pressed", String(file === chosen));
      tab.dataset.role = file.role;
      return tab;
    }));
    const node = el("div", { class: "viewer" }, tabs, image(item, version, ctx, chosen));
    return node;
  }

  function spriteSources(version) {
    const frames = imagesOf(version).filter((f) => f.role.startsWith("frame"));
    frames.sort((a, b) => a.role.localeCompare(b.role, undefined, { numeric: true }));
    if (frames.length >= 2) return { files: frames, sheet: null };
    const sheet = firstOf(version, "image/");
    return { files: sheet ? [sheet] : [], sheet };
  }

  function spriteFrames(item, version, ctx) {
    const { files, sheet } = spriteSources(version);
    if (!files.length || !ctx.fileUrl(files[0])) return placeholder(version, "no frames");
    const media = version.media || {};
    const hframes = Number(media.hframes) || 1;
    const vframes = Number(media.vframes) || 1;
    const count = sheet ? Number(media.frames) || hframes * vframes : files.length;
    const fps = Number(media.fps) || 12;
    const state = remember(item, { frame: 0, playing: false, onion: false, timer: null });
    clearInterval(state.timer);
    state.frame %= count;

    const canvas = el("canvas", { class: "picture", "data-frames": String(count) });
    const layer = el("div", { class: "regions" });
    const stage = el("div", { class: "stage", "data-file": files[0].role }, canvas, layer);
    const label = el("span", { class: "meta" });
    const images = files.map((file) => Object.assign(new Image(), { src: ctx.fileUrl(file) }));
    const pen = canvas.getContext("2d");

    function cell(index) {
      if (!sheet) return { img: images[index], x: 0, y: 0, w: images[index].naturalWidth, h: images[index].naturalHeight };
      const w = images[0].naturalWidth / hframes;
      const h = images[0].naturalHeight / vframes;
      return { img: images[0], x: (index % hframes) * w, y: Math.floor(index / hframes) * h, w, h };
    }

    function draw() {
      const now = cell(state.frame);
      canvas.width = now.w;
      canvas.height = now.h;
      pen.imageSmoothingEnabled = false;
      if (state.onion && count > 1) {
        const before = cell((state.frame + count - 1) % count);
        pen.globalAlpha = 0.35;
        pen.drawImage(before.img, before.x, before.y, before.w, before.h, 0, 0, now.w, now.h);
      }
      pen.globalAlpha = 1;
      pen.drawImage(now.img, now.x, now.y, now.w, now.h, 0, 0, now.w, now.h);
      canvas.dataset.frame = String(state.frame);
      label.textContent = `frame ${state.frame + 1} / ${count} at ${fps} fps`;
      const file = sheet ? sheet.role : files[state.frame].role;
      stage.dataset.file = file;
      drawRegions(layer, item, version, ctx, { file, frame: state.frame });
    }

    function step(by) {
      state.frame = (state.frame + by + count) % count;
      draw();
    }

    function play(on) {
      state.playing = on;
      clearInterval(state.timer);
      if (on) state.timer = setInterval(() => (canvas.isConnected ? step(1) : clearInterval(state.timer)), 1000 / fps);
    }

    const onion = el("input", { type: "checkbox", checked: state.onion, "data-control": "onion" });
    onion.addEventListener("change", () => {
      state.onion = onion.checked;
      draw();
    });
    const controls = el("div", { class: "controls" },
      button("◀", "previous", () => step(-1)),
      button("Play / pause", "play", () => play(!state.playing)),
      button("▶", "next", () => step(1)),
      el("label", {}, onion, " onion skin"), label);
    Promise.all(images.map((img) => img.decode())).then(() => {
      draw();
      if (state.playing) play(true);
    }, () => label.replaceChildren("a frame failed to load"));
    showDraft(layer, ctx);
    if (ctx.writable && version.id === item.current_version) {
      drawable(stage, layer, ctx, {
        get file() { return stage.dataset.file; },
        get frame() { return state.frame; },
      });
    }
    return el("div", { class: "viewer" }, stage, controls);
  }

  // Time notes for clips: a mark becomes the next note's region, a chip seeks to a note.
  function timeline(item, version, ctx, file, player) {
    const mark = button("Mark time", "mark", () => {
      const at = player.currentTime.toFixed(2);
      ctx.setDraft({ selector: `t=${at}`, file: file.role });
      pending.textContent = `next note at ${at} s`;
    });
    const draft = ctx.draft();
    const pending = el("span", { class: "meta", "data-pending": "1" },
      draft && TIME.test(draft.selector) ? `next note at ${TIME.exec(draft.selector)[1]} s` : "");
    const chips = ctx.regionNotes(version.id).filter((n) => TIME.test(n.region.selector)).map((note, index) => {
      const at = Number(TIME.exec(note.region.selector)[1]);
      const chip = button(`${index + 1}: ${at} s`, "seek", () => {
        player.currentTime = at;
      });
      chip.dataset.event = note.id;
      return chip;
    });
    return el("div", { class: "controls" }, ctx.writable ? mark : null, pending, ...chips);
  }

  function video(item, version, ctx) {
    const file = firstOf(version, "video/");
    const url = file && ctx.fileUrl(file);
    if (!url) return placeholder(version, "no playable video");
    const player = el("video", { class: "picture", src: url, controls: true, preload: "metadata", muted: true });
    return el("div", { class: "viewer" }, player, timeline(item, version, ctx, file, player));
  }

  const byKind = { ui, sprite_frames: spriteFrames, video };

  function view(item, version, ctx) {
    if (!version) return placeholder(null, "");
    const viewer = byKind[item.kind] || image;
    return viewer(item, version, ctx);
  }

  return { view, byKind, firstOf, placeholder, timeline, button };
})();
