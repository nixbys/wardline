/*
 * History comparison view (Phase 3 of the temporal-comparison work --
 * see the read-only GET /v1/globe/history endpoint's own docstring in
 * api/routers/globe.py for why this is scoped to usgs_earthquakes/
 * nasa_firms only). Two periods, two colors, rendered as plain Cesium
 * points -- not a live/continuous layer like aircraft.js et al., so it
 * has its own start/clear shape (compare-on-demand) rather than
 * start()/stop() polling.
 */
import * as Cesium from "cesium";
import { GlobeApi } from "../api.js";

const PERIOD_A_COLOR = "#7dd3fc";
const PERIOD_B_COLOR = "#fb7185";

export class HistoryLayer {
  constructor(viewer) {
    this.viewer = viewer;
    this.entities = [];
  }

  clear() {
    for (const entity of this.entities) this.viewer.entities.remove(entity);
    this.entities = [];
  }

  /** periodA/periodB are {start: Date, end: Date} (end exclusive). Returns
   * how many points each period actually had, for the HUD to report. */
  async compare({ connector, periodA, periodB }) {
    this.clear();
    const [a, b] = await Promise.all([
      GlobeApi.getHistory({ connector, start: periodA.start, end: periodA.end }),
      GlobeApi.getHistory({ connector, start: periodB.start, end: periodB.end }),
    ]);
    this._render(a, PERIOD_A_COLOR, "A");
    this._render(b, PERIOD_B_COLOR, "B");
    return { periodACount: a.length, periodBCount: b.length };
  }

  _render(docs, colorHex, label) {
    const color = Cesium.Color.fromCssColorString(colorHex);
    for (const doc of docs) {
      if (doc.latitude == null || doc.longitude == null) continue; // no coordinates to plot
      const entity = this.viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(doc.longitude, doc.latitude, 0),
        point: { pixelSize: 7, color, outlineColor: Cesium.Color.BLACK, outlineWidth: 1 },
        description: `Period ${label}: ${doc.title} (${doc.published_at})`,
      });
      this.entities.push(entity);
    }
  }
}

export const HISTORY_COLORS = { a: PERIOD_A_COLOR, b: PERIOD_B_COLOR };
