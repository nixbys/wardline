/*
 * Voice control via OpenAI Realtime over WebRTC. The ephemeral session
 * token comes from POST /v1/globe/realtime-session (wardline's own
 * OPENAI_API_KEY never reaches the browser -- see that endpoint's
 * docstring); everything from here down is the standard OpenAI Realtime
 * WebRTC client flow.
 *
 * Scope note: upstream ships 28 voice-controlled tools across cinematic
 * camera work, layer toggles, and cockpit mode. This ships two —
 * fly_to and toggle_layer — as a real, working slice rather than stubs
 * for the rest; see internal planning notes for where the remaining tool
 * surface actually belongs.
 */
import { GlobeApi } from "./api.js";

const TOOLS = [
  {
    type: "function",
    name: "fly_to",
    description: "Fly the camera to a named place on Earth.",
    parameters: {
      type: "object",
      properties: {
        latitude: { type: "number" },
        longitude: { type: "number" },
        label: { type: "string", description: "What to call this place, for the on-screen label." },
      },
      required: ["latitude", "longitude"],
    },
  },
  {
    type: "function",
    name: "toggle_layer",
    description: "Turn a live data layer on or off.",
    parameters: {
      type: "object",
      properties: {
        layer: { type: "string", enum: ["aircraft", "satellites", "vessels"] },
        enabled: { type: "boolean" },
      },
      required: ["layer", "enabled"],
    },
  },
];

export class VoiceSession {
  constructor({ onFlyTo, onToggleLayer, onStatus }) {
    this.onFlyTo = onFlyTo || (() => {});
    this.onToggleLayer = onToggleLayer || (() => {});
    this.onStatus = onStatus || (() => {});
    this.peerConnection = null;
    this.dataChannel = null;
    this.micStream = null;
  }

  async start() {
    const session = await GlobeApi.createRealtimeSession();
    const ephemeralKey = session.client_secret?.value;
    if (!ephemeralKey) throw new Error("realtime session response carried no client_secret");

    this.peerConnection = new RTCPeerConnection();

    const remoteAudio = document.createElement("audio");
    remoteAudio.autoplay = true;
    this.peerConnection.ontrack = (event) => {
      remoteAudio.srcObject = event.streams[0];
    };

    this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    for (const track of this.micStream.getTracks()) {
      this.peerConnection.addTrack(track, this.micStream);
    }

    this.dataChannel = this.peerConnection.createDataChannel("oai-events");
    this.dataChannel.addEventListener("open", () => {
      this.send({
        type: "session.update",
        session: {
          instructions:
            "You are the voice control for wardline's Live Globe. Keep responses brief. " +
            "Use fly_to to move the camera and toggle_layer to show/hide data layers.",
          tools: TOOLS,
        },
      });
      this.onStatus("connected");
    });
    this.dataChannel.addEventListener("message", (event) => this.handleServerEvent(JSON.parse(event.data)));

    const offer = await this.peerConnection.createOffer();
    await this.peerConnection.setLocalDescription(offer);

    const model = "gpt-realtime";
    const response = await fetch(`https://api.openai.com/v1/realtime?model=${model}`, {
      method: "POST",
      body: offer.sdp,
      headers: {
        Authorization: `Bearer ${ephemeralKey}`,
        "Content-Type": "application/sdp",
      },
    });
    if (!response.ok) throw new Error(`OpenAI Realtime handshake failed: ${response.status}`);
    await this.peerConnection.setRemoteDescription({ type: "answer", sdp: await response.text() });
  }

  stop() {
    this.dataChannel?.close();
    this.peerConnection?.close();
    for (const track of this.micStream?.getTracks() || []) track.stop();
    this.onStatus("disconnected");
  }

  send(event) {
    this.dataChannel?.send(JSON.stringify(event));
  }

  handleServerEvent(event) {
    if (event.type !== "response.function_call_arguments.done") return;
    let args;
    try {
      args = JSON.parse(event.arguments);
    } catch {
      return;
    }
    let result = { ok: true };
    if (event.name === "fly_to") {
      this.onFlyTo(args);
    } else if (event.name === "toggle_layer") {
      this.onToggleLayer(args);
    } else {
      result = { ok: false, error: `unknown tool ${event.name}` };
    }
    // Every function call needs a matching output back to the model, or
    // the conversation stalls waiting for one.
    this.send({
      type: "conversation.item.create",
      item: { type: "function_call_output", call_id: event.call_id, output: JSON.stringify(result) },
    });
    this.send({ type: "response.create" });
  }
}
