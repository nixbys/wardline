/*
 * Traffic (TomTom flow data, proxied through /v1/globe/traffic) is
 * click-to-query, not a continuous layer like the others -- TomTom's flow
 * API is a single point lookup, not a bulk/regional feed, so polling it
 * on a timer the way aircraft/vessels are would mean guessing which
 * points matter. Clicking the globe is a more honest match for the shape
 * of the underlying API.
 */
import * as Cesium from "cesium";
import { GlobeApi } from "../api.js";

export class TrafficLayer {
  constructor(viewer, { onResult, onError } = {}) {
    this.viewer = viewer;
    this.onResult = onResult || (() => {});
    this.onError = onError || (() => {});
    this.handler = null;
  }

  start() {
    this.handler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
    this.handler.setInputAction((click) => this.handleClick(click), Cesium.ScreenSpaceEventType.LEFT_CLICK);
  }

  stop() {
    this.handler?.destroy();
    this.handler = null;
  }

  async handleClick(click) {
    const cartesian = this.viewer.camera.pickEllipsoid(click.position, this.viewer.scene.globe.ellipsoid);
    if (!cartesian) return;
    const carto = Cesium.Cartographic.fromCartesian(cartesian);
    const lat = Cesium.Math.toDegrees(carto.latitude);
    const lon = Cesium.Math.toDegrees(carto.longitude);
    try {
      const flow = await GlobeApi.getTraffic(lat, lon);
      this.onResult({ lat, lon, flow });
    } catch (err) {
      this.onError(err);
    }
  }
}
