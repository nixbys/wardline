/*
 * Live vessels (AISStream, proxied through /v1/globe/aisstream). Unlike
 * aircraft, AISStream has no worldwide endpoint -- the backend opens a
 * short-lived bounding-box subscription per request (see globe.py's
 * _collect_aisstream), so this layer always polls the current viewport,
 * never "everything."
 */
import * as Cesium from "cesium";
import { GlobeApi } from "../api.js";

const POLL_INTERVAL_MS = 15_000; // ships move slowly -- no need to match the aircraft cadence

export class VesselLayer {
  constructor(viewer) {
    this.viewer = viewer;
    this.entities = new Map(); // mmsi -> Cesium.Entity
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
    if (!bbox) return;
    let data;
    try {
      data = await GlobeApi.getVessels(bbox);
    } catch {
      return;
    }
    const seen = new Set();

    for (const vessel of data.vessels || []) {
      seen.add(vessel.mmsi);
      const position = Cesium.Cartesian3.fromDegrees(vessel.lon, vessel.lat, 0);
      const orientation = Cesium.Transforms.headingPitchRollQuaternion(
        position,
        new Cesium.HeadingPitchRoll(Cesium.Math.toRadians(vessel.course || 0), 0, 0)
      );

      let entity = this.entities.get(vessel.mmsi);
      if (!entity) {
        entity = this.viewer.entities.add({
          id: `vessel-${vessel.mmsi}`,
          position,
          orientation,
          point: { pixelSize: 5, color: Cesium.Color.fromCssColorString("#34d399") },
          description: `MMSI ${vessel.mmsi} — ${vessel.speed ?? "?"} kn`,
        });
        this.entities.set(vessel.mmsi, entity);
      } else {
        entity.position = position;
        entity.orientation = orientation;
      }
    }

    for (const [mmsi, entity] of this.entities) {
      if (!seen.has(mmsi)) {
        this.viewer.entities.remove(entity);
        this.entities.delete(mmsi);
      }
    }
  }
}

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
