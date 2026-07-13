#!/usr/bin/env node
import { chromium } from "playwright";
import process from "node:process";

const baseUrl = process.env.TABLEX_BASE_URL ?? "http://127.0.0.1:8080";
const projectId = process.env.TABLEX_PROJECT_ID;
if (!projectId) throw new Error("TABLEX_PROJECT_ID is required");

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.route(`**/api/projects/${projectId}/jobs`, async (route) => {
    const response = await route.fetch();
    const jobs = await response.json();
    await route.fulfill({
      response,
      json: jobs.map((job) =>
        job.job_type === "run_prediction_pipeline"
          ? { ...job, status: "failed", error_message: "The prediction process could not start." }
          : job
      )
    });
  });
  await page.goto(`${baseUrl}/#/projects/${projectId}`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /^(Leaderboard|リーダーボード)$/ }).click();
  const predictButton = page
    .locator('button[title="Predict with this model"], button[title="このモデルで予測"]')
    .first();
  await predictButton.waitFor({ state: "visible" });
  await predictButton.click();

  const dialog = page.getByRole("dialog", { name: /Prediction|予測/ });
  const failure = dialog.getByText("The prediction process could not start.");
  await failure.waitFor({ state: "visible" });
  const activeOperationVisible = await dialog.locator(".prediction-operation-status").isVisible().catch(() => false);
  if (activeOperationVisible) throw new Error("Failed prediction was simultaneously shown as active");

  process.stdout.write(`${JSON.stringify({ status: "passed", activeOperationVisible })}\n`);
} finally {
  await browser.close();
}
