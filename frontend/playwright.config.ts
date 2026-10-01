import { defineConfig } from "@playwright/test";

const PORT = Number(process.env.PDE_E2E_PORT ?? 8799);
const chrome = process.env.PW_CHROMIUM_PATH ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
import { existsSync } from "node:fs";

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 30_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    launchOptions: existsSync(chrome) ? { executablePath: chrome } : {},
    acceptDownloads: true,
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    // fresh runtime/cache dirs so the test does not depend on earlier local state
    command: `cd .. && PDE_RUNTIME_DIR=$(mktemp -d) PDE_CACHE_DIR=$(mktemp -d) .venv/bin/python -m uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port ${PORT} --log-level warning`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    timeout: 60_000,
    reuseExistingServer: false,
  },
});
