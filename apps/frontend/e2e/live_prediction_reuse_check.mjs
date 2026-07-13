#!/usr/bin/env node
import { chromium } from "playwright";
import process from "node:process";

const baseUrl = process.env.TABLEX_BASE_URL ?? "http://127.0.0.1:8080";
const projectId = process.env.TABLEX_PROJECT_ID;

if (!projectId) throw new Error("TABLEX_PROJECT_ID is required");

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto(`${baseUrl}/#/projects/${projectId}`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /^(Leaderboard|リーダーボード)$/ }).click();
  const predictButtons = page.locator('button[title="Predict with this model"], button[title="このモデルで予測"]');
  const predictButton = predictButtons.first();
  await predictButton.waitFor({ state: "visible" });
  const disabledPredictButtons = await predictButtons.evaluateAll((buttons) =>
    buttons.filter((button) => button.disabled).length
  );
  if (disabledPredictButtons) {
    throw new Error(`${disabledPredictButtons} model Predict buttons are disabled before opening the workspace`);
  }
  await predictButton.click();

  const dialog = page.getByRole("dialog", { name: /Prediction|予測/ });
  await dialog.waitFor({ state: "visible" });
  const runButton = dialog.getByRole("button", { name: /Run prediction|予測を実行/ });
  const operationStatus = dialog.getByText(
    /Codex is reviewing the prediction inputs|Codexが予測入力を確認しています|Prediction execution accepted|予測実行を受理しました|canonical prediction pipeline|Codex is reviewing the actual prediction result|Codexが実際の予測結果を確認しています/
  );
  const readinessDeadline = Date.now() + 60_000;
  while (
    !(await runButton.isEnabled()) &&
    !(await operationStatus.isVisible().catch(() => false)) &&
    Date.now() < readinessDeadline
  ) {
    await page.waitForTimeout(250);
  }

  const automaticSummary = dialog
    .locator(".inline-alert")
    .filter({ hasText: /Tablex selected|自動選択しました/ })
    .first();
  await automaticSummary.waitFor({ state: "visible" });
  const automaticSummaryText = (await automaticSummary.innerText()).trim();
  const inputDetails = dialog.locator("details.prediction-upload-section");
  const inputDetailsOpen = await inputDetails.evaluate((element) => element.hasAttribute("open"));
  const runEnabled = await runButton.isEnabled();
  const restoredOperation = await operationStatus.isVisible().catch(() => false);
  if (!automaticSummaryText) throw new Error("Automatic prediction input summary is missing");
  if (inputDetailsOpen) throw new Error("Manual prediction input controls should be collapsed after automatic preparation");
  if (!runEnabled && !restoredOperation) {
    throw new Error(`Run prediction stayed disabled after project input preparation: ${automaticSummaryText}`);
  }

  await page.screenshot({ path: "/output/leaderboard_prediction_reuse_live.png", fullPage: false });
  process.stdout.write(
    `${JSON.stringify({ status: "passed", disabledPredictButtons, runEnabled, restoredOperation, inputDetailsOpen, automaticSummaryText })}\n`
  );
} catch (error) {
  const pages = browser.contexts().flatMap((context) => context.pages());
  const page = pages.at(-1);
  if (page) {
    await page.screenshot({ path: "/output/leaderboard_prediction_reuse_failure.png", fullPage: true });
    const body = await page.locator("body").innerText().catch(() => "");
    process.stderr.write(`${body.slice(0, 12_000)}\n`);
  }
  throw error;
} finally {
  await browser.close();
}
