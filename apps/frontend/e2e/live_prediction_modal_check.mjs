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
  const predictButton = page.locator('button[title="Predict with this model"], button[title="このモデルで予測"]').first();
  await predictButton.waitFor({ state: "visible" });
  await predictButton.click();
  const dialog = page.getByRole("dialog", { name: /Prediction|予測/ });
  await dialog.waitFor({ state: "visible" });
  const bounds = await dialog.boundingBox();
  if (!bounds || bounds.width < 300 || bounds.height < 200) {
    throw new Error(`Prediction dialog is not visibly framed: ${JSON.stringify(bounds)}`);
  }
  await page.screenshot({ path: "/output/leaderboard_prediction_modal_live.png", fullPage: false });
  await dialog.getByRole("button", { name: /Close|閉じる/ }).first().click();
  await dialog.waitFor({ state: "hidden" });
  process.stdout.write(`${JSON.stringify({ status: "passed", bounds })}\n`);
} finally {
  await browser.close();
}
