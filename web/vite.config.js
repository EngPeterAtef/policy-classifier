import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development (npm run dev) the page runs on port 5173 and forwards /api to the
// Python server on port 8000. In production the Python server serves web/dist itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
