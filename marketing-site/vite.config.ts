import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Pure static build. Output goes to ./dist and can be hosted on any
// static host (Cloudflare Pages, S3 + CloudFront, Azure Static Web Apps,
// Netlify, etc.) — no server runtime required.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 4321,
    host: true,
  },
  preview: {
    port: 4321,
  },
});
