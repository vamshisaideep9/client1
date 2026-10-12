import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e", testMatch: "client-draft.spec.ts", workers: 1,
  forbidOnly: true, retries: 0, timeout: 120_000, reporter: "list",
  outputDir: "../../build/client-draft/browser-results",
  projects: [{ name: "offline-chromium", metadata: { clientDraft: true } }],
  use: { screenshot: "only-on-failure", trace: "retain-on-failure" },
});
