import { defineConfig, devices } from "@playwright/test";

// The dev port is overridable so a busy port on a shared machine or runner can
// be avoided, and it defaults to 5273 because the Radar de Pliegos container
// occupies 5173 on the development machine.
const port = process.env.PLAYWRIGHT_PORT ?? "5273";
const baseURL = `http://localhost:${port}`;

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `pnpm dev --port ${port} --strictPort`,
    url: baseURL,
    // Never reuse: a stray dev server on this port would silently run the suite
    // against a different application, which is exactly what happened once with
    // another local project. Failing loudly is the safe behaviour everywhere.
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
