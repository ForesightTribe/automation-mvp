import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
	plugins: [react(), tailwindcss()],
	server: {
		proxy: {
			// Same-origin proxy to the backend, so the browser never makes a
			// cross-origin call to the forwarded :8000 codespace URL (which would
			// need its own separate GitHub-auth handshake — see chat).
			"/api": {
				target: "http://localhost:8000",
				changeOrigin: true,
			},
		},
	},
});
