/*
 * Thin client for wardline's /v1/globe/* proxy API (see
 * src/wardline/api/routers/globe.py). Every call here is unauthenticated
 * by design -- these endpoints are public/rate-limited, not bearer-token
 * gated, matching the rest of this page's "no login" access model.
 */
const API_BASE = (import.meta.env.VITE_WARDLINE_API_BASE || "http://localhost:8000").replace(/\/$/, "");

class GlobeApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "GlobeApiError";
    this.status = status;
  }
}

async function request(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    throw new GlobeApiError(`Could not reach ${API_BASE} -- is the wardline API running?`, 0);
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new GlobeApiError((data && data.detail) || response.statusText, response.status);
  }
  return data;
}

export const GlobeApi = {
  GlobeApiError,

  /** GET /v1/globe/config -- which layers are usable right now */
  getConfig() {
    return request("/v1/globe/config");
  },

  /** GET /v1/globe/opensky -- optionally bounded to a viewport bbox */
  getAircraft(bbox) {
    const qs = bbox
      ? `?lamin=${bbox.lamin}&lomin=${bbox.lomin}&lamax=${bbox.lamax}&lomax=${bbox.lomax}`
      : "";
    return request(`/v1/globe/opensky${qs}`);
  },

  /** GET /v1/globe/celestrak?format=tle -- raw TLE text for satellite.js to propagate */
  async getSatelliteTles(group = "stations") {
    const response = await fetch(`${API_BASE}/v1/globe/celestrak?group=${group}&format=tle`);
    if (!response.ok) throw new GlobeApiError("celestrak upstream unavailable", response.status);
    return response.text();
  },

  /** GET /v1/globe/aisstream -- requires a bbox, unlike the other layers */
  getVessels(bbox) {
    return request(
      `/v1/globe/aisstream?lamin=${bbox.lamin}&lomin=${bbox.lomin}&lamax=${bbox.lamax}&lomax=${bbox.lomax}`
    );
  },

  /** GET /v1/globe/traffic -- one point at a time (click-to-query, not a live layer) */
  getTraffic(lat, lon) {
    return request(`/v1/globe/traffic?lat=${lat}&lon=${lon}`);
  },

  /** POST /v1/globe/realtime-session -- mints an ephemeral OpenAI Realtime token */
  createRealtimeSession() {
    return request("/v1/globe/realtime-session", { method: "POST" });
  },
};
