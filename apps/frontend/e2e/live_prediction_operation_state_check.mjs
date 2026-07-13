#!/usr/bin/env node
import { chromium } from "playwright";
import process from "node:process";

const baseUrl = process.env.TABLEX_BASE_URL ?? "http://127.0.0.1:8080";
const projectId = process.env.TABLEX_PROJECT_ID;
if (!projectId) throw new Error("TABLEX_PROJECT_ID is required");

const targetJobId = "job_0dcce8955c5b";
const observedAt = new Date().toISOString();

function asRunningPrediction(job) {
  if (job.id !== targetJobId) return job;
  return {
    ...job,
    status: "running",
    started_at: new Date(Date.now() - 42_000).toISOString(),
    updated_at: observedAt,
    ended_at: null,
    output: {},
    context: {
      ...job.context,
      execution_progress: {
        schema_version: "prediction_execution_progress.v1",
        phase: "pipeline_running",
        started_at: new Date(Date.now() - 42_000).toISOString(),
        last_heartbeat_at: observedAt,
        elapsed_seconds: 42,
        return_code: null
      }
    }
  };
}

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.route(`**/api/projects/${projectId}/jobs`, async (route) => {
    const response = await route.fetch();
    const jobs = await response.json();
    await route.fulfill({ response, json: jobs.map(asRunningPrediction) });
  });
  await page.route(`**/api/jobs/${targetJobId}`, async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: asRunningPrediction(await response.json()) });
  });

  await page.goto(`${baseUrl}/#/projects/${projectId}`, { waitUntil: "domcontentloaded" });
  const activityCard = page.locator(".agent-worker-card").filter({
    hasText: /canonical prediction pipeline|予測.*pipeline|Prediction/
  }).first();
  await activityCard.waitFor({ state: "visible" });

  await page.getByRole("button", { name: /^(Leaderboard|リーダーボード)$/ }).click();
  await page.locator('button[title="Predict with this model"], button[title="このモデルで予測"]').first().click();
  const dialog = page.getByRole("dialog", { name: /Prediction|予測/ });
  await dialog.getByText(/canonical prediction pipeline.*running|canonical prediction pipelineを実行中/).waitFor({
    state: "visible"
  });
  await dialog.getByText(/Pipeline runtime: 42s|pipeline実行時間: 42秒/).waitFor({ state: "visible" });
  const vagueStatusVisible = await dialog
    .getByText(/Codex is managing this prediction|Codexがこの予測を管理しています/)
    .isVisible()
    .catch(() => false);
  if (vagueStatusVisible) throw new Error("The prediction dialog fell back to the vague legacy status");

  await page.screenshot({ path: "/output/leaderboard_prediction_running_state.png", fullPage: false });
  process.stdout.write(`${JSON.stringify({ status: "passed", vagueStatusVisible })}\n`);
} finally {
  await browser.close();
}
