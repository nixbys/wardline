import { defineConfig } from "vite";
import cesium from "vite-plugin-cesium";

// Deployed at a `/globe/` path alongside `web/`'s own root (see README.md's
// "Deployment" section) -- `base` matches that so built asset URLs resolve
// correctly wherever the reverse proxy mounts this app.
export default defineConfig({
  base: "/globe/",
  plugins: [cesium()],
  server: {
    port: 4173,
  },
  build: {
    outDir: "dist",
  },
});
