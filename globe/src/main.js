import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { GlobeApi } from "./api.js";
import { AircraftLayer } from "./layers/aircraft.js";
import { SatelliteLayer } from "./layers/satellites.js";
import { VesselLayer } from "./layers/vessels.js";
import { TrafficLayer } from "./layers/traffic.js";
import { Hud } from "./hud.js";
import { VoiceSession } from "./voice.js";

const ionToken = import.meta.env.VITE_CESIUM_ION_TOKEN;
if (ionToken) Cesium.Ion.defaultAccessToken = ionToken;

// Esri World Imagery: the same keyless, public-app-friendly basemap
// upstream uses as its no-account default (see DATA_SOURCES.md) --
// avoids requiring every viewer of this public page to have a Cesium ion
// account just to see a globe. Terrain stays the Cesium default
// (EllipsoidTerrainProvider, also keyless) unless VITE_CESIUM_ION_TOKEN is set.
const viewer = new Cesium.Viewer("cesiumContainer", {
  baseLayer: Cesium.ImageryLayer.fromProviderAsync(
    Cesium.ArcGisMapServerImageryProvider.fromUrl(
      "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer"
    )
  ),
  terrainProvider: ionToken ? await Cesium.createWorldTerrainAsync() : undefined,
  timeline: false,
  animation: false,
  geocoder: false,
  homeButton: false,
  sceneModePicker: false,
  navigationHelpButton: false,
  fullscreenButton: false,
  baseLayerPicker: false,
});
viewer.scene.globe.enableLighting = true;

const toastStack = document.getElementById("toastStack");
function toast(message, variant = "") {
  const el = document.createElement("div");
  el.className = `toast ${variant ? `toast--${variant}` : ""}`.trim();
  el.textContent = message;
  toastStack.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

const layers = {
  aircraft: new AircraftLayer(viewer),
  satellites: new SatelliteLayer(viewer),
  vessels: new VesselLayer(viewer),
};

const trafficLayer = new TrafficLayer(viewer, {
  onResult: ({ lat, lon, flow }) => {
    const segment = flow.flowSegmentData;
    if (!segment) return toast(`No traffic data at ${lat.toFixed(2)}, ${lon.toFixed(2)}`);
    toast(
      `Traffic near ${lat.toFixed(2)}, ${lon.toFixed(2)}: ${segment.currentSpeed}/${segment.freeFlowSpeed} km/h`
    );
  },
  onError: () => toast("Traffic lookup failed", "danger"),
});

const hud = new Hud(document.getElementById("hud"), {
  onLayerToggle: (name, enabled) => setLayerEnabled(name, enabled),
});

function setLayerEnabled(name, enabled) {
  const layer = layers[name];
  if (!layer) return;
  if (enabled) layer.start();
  else layer.stop();
}

async function boot() {
  hud.setStatus("Connecting to wardline…");
  let config;
  try {
    config = await GlobeApi.getConfig();
  } catch (err) {
    hud.setStatus("Could not reach the wardline API");
    toast(err.message, "danger");
    return;
  }

  // Aircraft/satellites need no key, so they're auto-started; traffic is a
  // click handler with no ongoing request cost, so it's auto-started too.
  // Vessels polls a rate-limited third-party API continuously -- available
  // once AISSTREAM_API_KEY is configured, but left opt-in (unchecked until
  // the viewer turns it on) rather than every visitor's browser silently
  // starting that poll on page load.
  const availability = {
    aircraft: { available: config.layers.opensky, running: config.layers.opensky },
    satellites: { available: config.layers.celestrak, running: config.layers.celestrak },
    vessels: {
      available: config.layers.aisstream,
      running: false,
      reason: "AISSTREAM_API_KEY not set on the server",
    },
    traffic: { available: config.layers.traffic, running: config.layers.traffic, reason: "TOMTOM_API_KEY not set on the server" },
  };
  hud.setLayers(availability);
  hud.setStatus("Live");

  if (availability.aircraft.running) layers.aircraft.start();
  if (availability.satellites.running) layers.satellites.start();
  if (availability.traffic.running) trafficLayer.start();

  if (config.layers.voice) {
    const voiceButton = document.getElementById("voiceToggle");
    voiceButton.hidden = false;
    let session = null;
    voiceButton.addEventListener("click", async () => {
      if (session) {
        session.stop();
        session = null;
        voiceButton.classList.remove("pill--active");
        voiceButton.textContent = "🎙 Voice";
        return;
      }
      session = new VoiceSession({
        onFlyTo: ({ latitude, longitude, label }) => {
          viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(longitude, latitude, 500_000),
          });
          if (label) toast(`Flying to ${label}`);
        },
        onToggleLayer: ({ layer, enabled }) => {
          setLayerEnabled(layer, enabled);
          hud.setLayerChecked(layer, enabled);
        },
        onStatus: (status) => toast(`Voice: ${status}`),
      });
      try {
        await session.start();
        voiceButton.classList.add("pill--active");
        voiceButton.textContent = "🎙 Listening";
      } catch (err) {
        toast(`Voice control failed: ${err.message}`, "danger");
        session = null;
      }
    });
  }
}

boot();
