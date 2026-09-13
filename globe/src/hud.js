/*
 * Layer toggles + status + required attribution. Every source rendered
 * here carries a citation requirement (OpenSky's academic license,
 * CelesTrak's citation request, TomTom's "when live mode activates"
 * clause) -- see the upstream project's own DATA_SOURCES.md, which this
 * follows the spirit of rather than duplicating verbatim.
 */
const ATTRIBUTIONS = [
  ["OpenSky Network", "https://opensky-network.org"],
  ["CelesTrak (Dr. T.S. Kelso)", "https://celestrak.org"],
  ["AISStream.io", "https://aisstream.io"],
  ["TomTom Traffic", "https://developer.tomtom.com"],
  ["Esri World Imagery", "https://www.esri.com"],
];

export class Hud {
  constructor(root, { onLayerToggle } = {}) {
    this.root = root;
    this.onLayerToggle = onLayerToggle || (() => {});
    this.statusEl = null;
    this.render();
  }

  render() {
    this.root.innerHTML = `
      <h2>Layers</h2>
      <div id="hudLayers"></div>
      <div class="hud__status" id="hudStatus"></div>
      <div class="hud__attribution">
        Live data: ${ATTRIBUTIONS.map(([name, url]) => `<a href="${url}" target="_blank" rel="noreferrer">${name}</a>`).join(", ")}.
        Inspired by <a href="https://github.com/bilawalsidhu/gods-eye-view" target="_blank" rel="noreferrer">
        God's Eye View</a> (MIT).
      </div>
    `;
    this.statusEl = this.root.querySelector("#hudStatus");
  }

  /** `layers` is { name: { available: bool, running: bool, reason?: string } }.
   * `available` (server has the key configured) and `running` (this layer
   * has actually been start()-ed) are kept separate on purpose: a
   * key being configured doesn't mean every visitor's browser should
   * silently start polling a rate-limited third-party API on page load. */
  setLayers(layers) {
    const container = this.root.querySelector("#hudLayers");
    container.innerHTML = Object.entries(layers)
      .map(
        ([name, { available, running, reason }]) => `
        <div class="hud__layer ${available ? "" : "hud__layer--disabled"}">
          <label>
            <input type="checkbox" data-layer="${name}" ${running ? "checked" : ""} ${available ? "" : "disabled"} />
            ${label(name)}
          </label>
          ${available ? "" : `<span title="${reason || "not configured"}">—</span>`}
        </div>`
      )
      .join("");
    container.querySelectorAll("input[data-layer]").forEach((input) => {
      input.addEventListener("change", () => this.onLayerToggle(input.dataset.layer, input.checked));
    });
  }

  setLayerChecked(name, checked) {
    const input = this.root.querySelector(`input[data-layer="${name}"]`);
    if (input) input.checked = checked;
  }

  setStatus(text) {
    this.statusEl.textContent = text;
  }
}

function label(name) {
  return { aircraft: "Aircraft", satellites: "Satellites", vessels: "Vessels", traffic: "Traffic (click map)" }[name] || name;
}
