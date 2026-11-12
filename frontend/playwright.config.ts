import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: "http://localhost:5273",
    trace: "retain-on-failure",
  },
  webServer: {
    // Port 5273, not the default 5173: the Radar de Pliegos container occupies
    // 5173 on the development machine (and a stray dev server sits on 5174),
    // and a pinned port keeps runs deterministic.
    command: "pnpm dev --port 5273 --strictPort",
    url: "http://localhost:5273",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
