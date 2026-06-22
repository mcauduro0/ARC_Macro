import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import path from "path";

const templateRoot = path.resolve(import.meta.dirname);

export default defineConfig({
  root: templateRoot,
  // The react plugin transforms the .tsx client component tests; server .ts tests pass through untouched.
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(templateRoot, "client", "src"),
      "@shared": path.resolve(templateRoot, "shared"),
      "@assets": path.resolve(templateRoot, "attached_assets"),
    },
  },
  test: {
    // node env throughout: the client component tests render via react-dom/server (renderToStaticMarkup),
    // so no jsdom is needed — keeping CI's frozen-lockfile install dependency-free.
    environment: "node",
    include: ["server/**/*.test.ts", "server/**/*.spec.ts", "client/**/*.test.tsx", "shared/**/*.test.ts"],
  },
});
