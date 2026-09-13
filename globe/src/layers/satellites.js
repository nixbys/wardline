/*
 * Live satellites (CelesTrak TLEs, proxied through /v1/globe/celestrak,
 * propagated client-side with satellite.js -- the same SGP4 library
 * gods-eye-view itself depends on for this exact job). Real orbital
 * mechanics, not a static snapshot: positions are recomputed every frame
 * from each satellite's actual elements, not re-fetched from the network.
 */
import * as Cesium from "cesium";
import * as satellite from "satellite.js";
import { GlobeApi } from "../api.js";

const TLE_REFRESH_MS = 2 * 60 * 60 * 1000; // elements barely drift within a couple hours
const REPOSITION_INTERVAL_MS = 1000;

export class SatelliteLayer {
  constructor(viewer, { group = "stations" } = {}) {
    this.viewer = viewer;
    this.group = group;
    this.satrecs = []; // [{ name, satrec, entity }]
    this.refreshTimer = null;
    this.tickTimer = null;
  }

  start() {
    this.refresh();
    this.refreshTimer = setInterval(() => this.refresh(), TLE_REFRESH_MS);
    this.tickTimer = setInterval(() => this.reposition(), REPOSITION_INTERVAL_MS);
  }

  stop() {
    clearInterval(this.refreshTimer);
    clearInterval(this.tickTimer);
    for (const { entity } of this.satrecs) this.viewer.entities.remove(entity);
    this.satrecs = [];
  }

  async refresh() {
    let tleText;
    try {
      tleText = await GlobeApi.getSatelliteTles(this.group);
    } catch {
      return; // keep showing whatever's already tracked rather than blanking out
    }
    for (const { entity } of this.satrecs) this.viewer.entities.remove(entity);
    this.satrecs = parseTleGroups(tleText).map(({ name, line1, line2 }) => {
      const satrec = satellite.twoline2satrec(line1, line2);
      const entity = this.viewer.entities.add({
        id: `satellite-${name}`,
        position: new Cesium.ConstantPositionProperty(Cesium.Cartesian3.ZERO),
        point: { pixelSize: 4, color: Cesium.Color.fromCssColorString("#facc15") },
        label: {
          text: name,
          font: "10px sans-serif",
          pixelOffset: new Cesium.Cartesian2(8, 0),
          fillColor: Cesium.Color.WHITE,
          showBackground: true,
          backgroundColor: Cesium.Color.BLACK.withAlpha(0.5),
          show: false, // satellite labels get noisy fast -- toggled on via selection
        },
      });
      entity.label.show = new Cesium.CallbackProperty(() => this.viewer.selectedEntity === entity, false);
      return { name, satrec, entity };
    });
  }

  reposition() {
    if (this.satrecs.length === 0) return;
    const now = new Date();
    const gmst = satellite.gstime(now);
    for (const { satrec, entity } of this.satrecs) {
      const result = satellite.propagate(satrec, now);
      if (!result.position) continue; // decayed/invalid element set -- skip this tick
      const geodetic = satellite.eciToGeodetic(result.position, gmst);
      entity.position = Cesium.Cartesian3.fromRadians(
        geodetic.longitude,
        geodetic.latitude,
        geodetic.height * 1000 // km -> m
      );
    }
  }
}

function parseTleGroups(tleText) {
  const lines = tleText.split("\n").map((l) => l.trim()).filter(Boolean);
  const groups = [];
  for (let i = 0; i + 2 < lines.length; i += 3) {
    const [name, line1, line2] = lines.slice(i, i + 3);
    if (line1?.startsWith("1 ") && line2?.startsWith("2 ")) {
      groups.push({ name, line1, line2 });
    }
  }
  return groups;
}
