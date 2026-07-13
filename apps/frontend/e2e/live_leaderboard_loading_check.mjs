#!/usr/bin/env node
import { chromium } from "playwright";
import process from "node:process";

const baseUrl = process.env.TABLEX_BASE_URL ?? "http://127.0.0.1:8080";
const projectId = process.env.TABLEX_PROJECT_ID;
if (!projectId) throw new Error("TABLEX_PROJECT_ID is required");

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.route(`**/api/projects/${projectId}/leaderboard`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await page.goto(`${baseUrl}/#/projects/${projectId}`, { waitUntil: "domcontentloaded" });
  const startedAt = Date.now();
  await page.getByRole("button", { name: /^(Leaderboard|リーダーボード)$/ }).click();
  const loading = page.getByText(/Loading ranked models|モデルランキングを読み込んでいます/).first();
  await loading.waitFor({ state: "visible", timeout: 1000 });
  const falseEmptyVisible = await page
    .getByText(/No ranked models yet|順位付けされたモデルはまだありません/)
    .isVisible()
    .catch(() => false);
  if (falseEmptyVisible) throw new Error("Leaderboard showed an empty state while its request was still loading");

  const ranked = page.getByRole("heading", { name: /models ranked|モデル/ }).first();
  await ranked.waitFor({ state: "visible", timeout: 5000 });
  const elapsedMs = Date.now() - startedAt;
  await page.screenshot({ path: "/output/leaderboard_loaded_live.png", fullPage: false });

  const errorPage = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await errorPage.route(`**/api/projects/${projectId}/leaderboard`, (route) =>
    route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"Leaderboard unavailable"}' })
  );
  await errorPage.goto(`${baseUrl}/#/projects/${projectId}`, { waitUntil: "domcontentloaded" });
  await errorPage.getByRole("button", { name: /^(Leaderboard|リーダーボード)$/ }).click();
  const loadError = errorPage.getByRole("heading", {
    name: /Ranked models could not be loaded|モデルランキングを読み込めませんでした/
  });
  await loadError.waitFor({ state: "visible", timeout: 5000 });
  const emptyVisibleAfterError = await errorPage
    .getByText(/No ranked models yet|順位付けされたモデルはまだありません/)
    .isVisible()
    .catch(() => false);
  if (emptyVisibleAfterError) throw new Error("Leaderboard showed an empty state after a request failure");
  process.stdout.write(
    `${JSON.stringify({ status: "passed", falseEmptyVisible, emptyVisibleAfterError, elapsedMs })}\n`
  );
} finally {
  await browser.close();
}
