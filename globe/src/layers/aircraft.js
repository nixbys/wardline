/*
 * Live aircraft (OpenSky, proxied through /v1/globe/opensky). Re-polls on
 * an interval and reconciles into one Cesium Entity per ICAO24 address --
 * updating existing entities' positions rather than tearing everything
 * down each poll, so in-flight camera tracking/selection isn't disrupted.
 */
import * as Cesium from "cesium";
import { GlobeApi } from "../api.js";

const POLL_INTERVAL_MS = 10_000; // stays above the backend's own cache TTL

export class AircraftLayer {
  constructor(viewer) {
    this.viewer = viewer;
    this.entities = new Map(); // icao24 -> Cesium.Entity
    this.timer = null;
  }

  start() {
    this.poll();
    this.timer = setInterval(() => this.poll(), POLL_INTERVAL_MS);
  }

  stop() {
    clearInterval(this.timer);
    for (const entity of this.entities.values()) this.viewer.entities.remove(entity);
    this.entities.clear();
  }

  async poll() {
    const bbox = viewportBbox(this.viewer);
    let data;
    try {
      data = await GlobeApi.getAircraft(bbox);
    } catch {
      return; // a single failed poll shouldn't clear what's already shown
    }
    const states = data.states || [];
    const seen = new Set();

    for (const state of states) {
      const [icao24, callsign, , , , lon, lat, baroAltitude, , , trueTrack] = state;
      if (lat == null || lon == null) continue; // no last-known position to plot
      seen.add(icao24);

      const position = Cesium.Cartesian3.fromDegrees(lon, lat, baroAltitude || 0);
      const heading = Cesium.Math.toRadians(trueTrack || 0);
      const orientation = Cesium.Transforms.headingPitchRollQuaternion(
        position,
        new Cesium.HeadingPitchRoll(heading, 0, 0)
      );

      let entity = this.entities.get(icao24);
      if (!entity) {
        entity = this.viewer.entities.add({
          id: `aircraft-${icao24}`,
          position,
          orientation,
          point: { pixelSize: 6, color: Cesium.Color.fromCssColorString("#7dd3fc") },
          label: {
            text: (callsign || icao24).trim(),
            font: "11px sans-serif",
            pixelOffset: new Cesium.Cartesian2(10, 0),
            fillColor: Cesium.Color.WHITE,
            showBackground: true,
            backgroundColor: Cesium.Color.BLACK.withAlpha(0.5),
          },
          description: `ICAO24 ${icao24}${callsign ? ` — ${callsign.trim()}` : ""}`,
        });
        this.entities.set(icao24, entity);
      } else {
        entity.position = position;
        entity.orientation = orientation;
      }
    }

    // Drop anything not present in this poll -- landed, out of range, or
    // OpenSky simply lost its last-known fix.
    for (const [icao24, entity] of this.entities) {
      if (!seen.has(icao24)) {
        this.viewer.entities.remove(entity);
        this.entities.delete(icao24);
      }
    }
  }
}

/** OpenSky rejects a partial bbox, so this is all-or-nothing. Bounding the
 * request to the current viewport keeps response size and OpenSky's own
 * rate limit sane instead of always requesting the whole planet's traffic. */
function viewportBbox(viewer) {
  const rectangle = viewer.camera.computeViewRectangle();
  if (!rectangle) return null;
  return {
    lamin: Cesium.Math.toDegrees(rectangle.south),
    lomin: Cesium.Math.toDegrees(rectangle.west),
    lamax: Cesium.Math.toDegrees(rectangle.north),
    lomax: Cesium.Math.toDegrees(rectangle.east),
  };
}
