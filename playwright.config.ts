// Playwright e2e config for the ARC 2.0 Mesa UI.
//
// NOTE: @playwright/test is intentionally NOT in package.json — the pinned-pnpm/virtual-store constraint in
// this repo makes adding it unsafe for the frozen-lockfile CI install. This file + e2e/ are excluded from
// tsconfig and from the vitest run, so they never affect `pnpm check` or the CI gate. To enable e2e locally:
//
//   pnpm add -D @playwright/test && pnpm exec playwright install chromium
//   pnpm test:e2e
//
// The webServer boots the full app (Vite + Node/tRPC). The bridge (uvicorn arc.webapi.app) is optional —
// the smoke spec tolerates the bridge-offline state, asserting the shell/nav render either way.
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: process.env.ARC_E2E_BASE_URL ?? "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "pnpm dev",
    url: process.env.ARC_E2E_BASE_URL ?? "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
