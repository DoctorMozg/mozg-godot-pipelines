// Builds each screen from screens.json; text comes only from strings.json (l10n keys).
const load = (name) => fetch(name).then((response) => response.json());

Promise.all([load("screens.json"), load("strings.json"), load("fixtures.json")]).then(
  ([screens, strings, fixtures]) => {
    const pick = (id, values) => {
      const select = document.getElementById(id);
      select.replaceChildren(...values.map((value) => new Option(value, value)));
      select.onchange = draw;
      return select;
    };
    const screen = pick("screen", Object.keys(screens.screens));
    const state = pick("state", screens.states);
    const size = pick("size", screens.sizes);

    function draw() {
      const shown = screens.screens[screen.value];
      const [width, height] = size.value.split("x").map(Number);
      const frame = document.getElementById("frame");
      frame.style.width = `${width / 2}px`;
      frame.style.height = `${height / 2}px`;
      frame.dataset.state = state.value;
      frame.replaceChildren(
        ...shown.components.map((part) => {
          const box = document.createElement("div");
          box.className = "component";
          box.dataset.focus = String(part.name === shown.initial_focus);
          const key = part.string;
          box.textContent = key ? (strings[key] ?? `[${key}]`) : `${part.class} ${part.name}`;
          box.title = JSON.stringify(fixtures[part.name] ?? {});
          return box;
        }),
      );
    }
    draw();
  },
);
