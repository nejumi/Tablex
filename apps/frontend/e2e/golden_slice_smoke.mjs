#!/usr/bin/env node
import { chromium, request as playwrightRequest } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const repoRoot = path.resolve(new URL("../../..", import.meta.url).pathname);
const outputDir = path.join(repoRoot, "output", "playwright");

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : null;
      server.close(() => {
        if (!port) reject(new Error("Could not allocate a local port"));
        else resolve(port);
      });
    });
  });
}

async function waitForHttp(url, { timeoutMs = 60_000, label = url } = {}) {
  const start = Date.now();
  let lastError = "";
  while (Date.now() - start < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
      lastError = `${response.status} ${response.statusText}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for ${label}: ${lastError}`);
}

async function waitForJob(apiBase, jobId, { timeoutMs = 90_000 } = {}) {
  const start = Date.now();
  let latest = null;
  while (Date.now() - start < timeoutMs) {
    const response = await fetch(`${apiBase}/api/jobs/${jobId}`);
    if (!response.ok) throw new Error(`Job ${jobId} status failed: ${response.status} ${await response.text()}`);
    latest = await response.json();
    if (latest.status === "succeeded") return latest;
    if (latest.status === "failed" || latest.status === "cancelled") {
      throw new Error(`Job ${jobId} ended with ${latest.status}: ${JSON.stringify(latest.output ?? latest.failure_reason)}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for job ${jobId}: ${JSON.stringify(latest)}`);
}

function startProcess(command, args, options) {
  let stopping = false;
  const child = spawn(command, args, {
    cwd: repoRoot,
    env: options.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const stdout = [];
  const stderr = [];
  child.stdout.on("data", (chunk) => stdout.push(chunk.toString()));
  child.stderr.on("data", (chunk) => stderr.push(chunk.toString()));
  child.on("exit", (code, signal) => {
    if (options.allowExit || stopping) return;
    if (code !== null && code !== 0) {
      console.error(`${options.label} exited with ${code}`);
      console.error(stderr.join("").slice(-4000));
    } else if (signal) {
      console.error(`${options.label} exited with signal ${signal}`);
    }
  });
  return {
    child,
    stdout,
    stderr,
    async stop() {
      if (child.exitCode !== null || child.signalCode !== null) return;
      stopping = true;
      child.kill("SIGTERM");
      await new Promise((resolve) => {
        const timer = setTimeout(() => {
          if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
          resolve();
        }, 3000);
        child.once("exit", () => {
          clearTimeout(timer);
          resolve();
        });
      });
    },
  };
}

async function createProjectAndUpload(apiBase) {
  const projectResponse = await fetch(`${apiBase}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "E2E Golden Slice", description: "Browser smoke project." }),
  });
  if (!projectResponse.ok) throw new Error(`Project create failed: ${projectResponse.status} ${await projectResponse.text()}`);
  const project = await projectResponse.json();
  const form = new FormData();
  form.append(
    "files",
    new Blob(["customer_id,debt_to_income,recent_delinquency_count,TARGET\nC001,0.22,0,0\nC002,0.61,2,1\n"], {
      type: "text/csv",
    }),
    "application_train.csv",
  );
  form.append(
    "files",
    new Blob(["customer_id,months_observed\nC001,18\nC002,42\n"], { type: "text/csv" }),
    "bureau.csv",
  );
  const uploadResponse = await fetch(`${apiBase}/api/projects/${project.id}/datasets/upload-bundle`, {
    method: "POST",
    body: form,
  });
  if (!uploadResponse.ok) throw new Error(`Upload failed: ${uploadResponse.status} ${await uploadResponse.text()}`);
  const uploadJob = await uploadResponse.json();
  await fetch(`${apiBase}/api/jobs/${uploadJob.id}/run`, { method: "POST" });
  const completedUpload = await waitForJob(apiBase, uploadJob.id);
  const postUploadProjectResponse = await fetch(`${apiBase}/api/projects/${project.id}`);
  const postUploadProject = await postUploadProjectResponse.json();
  if (postUploadProject.primary_dataset_snapshot_id !== null) {
    throw new Error("Upload without primary_filename should leave primary_dataset_snapshot_id open");
  }
  return { project, completedUpload };
}

async function runSeed(env, projectId) {
  const completed = spawnSync(
    path.join(repoRoot, ".venv", "bin", "python"),
    [path.join(repoRoot, "apps", "frontend", "e2e", "seed_golden_slice.py"), "--project-id", projectId],
    {
      cwd: repoRoot,
      env,
      encoding: "utf-8",
    },
  );
  if (completed.status !== 0) {
    throw new Error(`Seed failed:\n${completed.stdout}\n${completed.stderr}`);
  }
  const line = completed.stdout.trim().split(/\n/).filter(Boolean).at(-1);
  if (!line) throw new Error("Seed did not print JSON output");
  return JSON.parse(line);
}

async function createPredictionBatch(apiBase, seed) {
  const response = await fetch(`${apiBase}/api/pilot-deployments/${seed.deployment_id}/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_snapshot_id: seed.dataset_snapshot_id, as_of: "2026-07-08T00:00:00Z", timeout_seconds: 120 }),
  });
  if (!response.ok) throw new Error(`Pilot predict failed: ${response.status} ${await response.text()}`);
  const job = await response.json();
  await fetch(`${apiBase}/api/jobs/${job.id}/run`, { method: "POST" });
  return waitForJob(apiBase, job.id, { timeoutMs: 120_000 });
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const backendPort = await freePort();
  const frontendPort = await freePort();
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), "tablex-e2e-golden-"));
  const dataDir = path.join(tempRoot, "data");
  const backendBase = `http://127.0.0.1:${backendPort}`;
  const frontendBase = `http://127.0.0.1:${frontendPort}`;
  const env = {
    ...process.env,
    PYTHONPATH: path.join(repoRoot, "apps", "backend"),
    HARNESS_DATA_DIR: dataDir,
    HARNESS_ARTIFACT_ROOT: path.join(dataDir, "artifacts"),
    HARNESS_DATABASE_URL: `sqlite:///${path.join(dataDir, "metadata", "app.db")}`,
    HARNESS_CORS_ORIGINS: `${frontendBase},http://localhost:${frontendPort}`,
    TABLEX_AUTH_ENABLED: "false",
    TABLEX_API_AGENT_SESSION_SUPERVISOR_ENABLED: "false",
    TABLEX_LOCAL_WORKER_ENABLED: "true",
    TABLEX_LOCAL_WORKER_INTERVAL_SECONDS: "0.2",
    TABLEX_MARIMO_MAX_SESSIONS: "2",
    VITE_API_BASE: backendBase,
  };

  const backend = startProcess(
    path.join(repoRoot, ".venv", "bin", "python"),
    ["-m", "uvicorn", "tabular_harness.main:app", "--app-dir", "apps/backend", "--host", "127.0.0.1", "--port", String(backendPort)],
    { env, label: "backend" },
  );
  const frontend = startProcess(
    "npm",
    ["--prefix", "apps/frontend", "run", "dev", "--", "--host", "127.0.0.1", "--port", String(frontendPort)],
    { env, label: "frontend" },
  );

  let browser = null;
  let api = null;
  try {
    await waitForHttp(`${backendBase}/health`, { label: "backend health" });
    const { project, completedUpload } = await createProjectAndUpload(backendBase);
    const seed = await runSeed(env, project.id);
    const predictionJob = await createPredictionBatch(backendBase, seed);
    await waitForHttp(frontendBase, { label: "frontend dev server" });

    browser = await chromium.launch({ headless: process.env.PLAYWRIGHT_HEADLESS !== "0" });
    api = await playwrightRequest.newContext();
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    page.setDefaultTimeout(90_000);
    await page.goto(`${frontendBase}/#/projects/${project.id}`, { waitUntil: "domcontentloaded" });
    await page.getByText("E2E Golden Slice").first().waitFor();
    await page.getByText("Open model diagnostics notebook").click();
    await page.locator("iframe.native-marimo-frame").waitFor({ state: "attached", timeout: 120_000 });
    await page.getByText("Golden slice model diagnostics notebook").first().waitFor();
    await page.screenshot({ path: path.join(outputDir, "0121_i6_notebook_from_chat.png"), fullPage: true });

    await page.getByRole("button", { name: /^(Leaderboard|リーダーボード)$/ }).click();
    await page.getByText("Golden slice logistic model").first().waitFor();
    await page.getByText("Deterministic credit-risk model").first().waitFor();
    const bundleResponse = await api.get(`${backendBase}/api/experiment-runs/${seed.run_id}/pipeline-bundle`);
    if (bundleResponse.status() !== 200) {
      throw new Error(`Pipeline bundle download returned ${bundleResponse.status()}`);
    }
    const bundleBody = await bundleResponse.body();
    if (bundleBody[0] !== 0x50 || bundleBody[1] !== 0x4b) {
      throw new Error("Pipeline bundle did not return zip content");
    }
    await page.locator('button[title*="Notebook"], button[title*="notebook"], button[title*="ノートブック"], button[title*="Notebookを開く"]').last().click();
    await page.locator("iframe.native-marimo-frame").waitFor({ state: "attached", timeout: 120_000 });
    await page.getByText("Golden slice model diagnostics notebook").first().waitFor();
    await page.screenshot({ path: path.join(outputDir, "0121_i6_notebook_from_leaderboard.png"), fullPage: true });

    await page.getByRole("button", { name: /^(Leaderboard|リーダーボード)$/ }).click();
    await page.getByText(/Pilot|仮運用/).first().waitFor();
    await page.getByText(/ROC[-_\s]?AUC|roc_auc/i).first().waitFor();
    await page.locator('button[title="Predict with this model"], button[title="このモデルで予測"]').first().click();
    const predictionDialog = page.getByRole("dialog", { name: /Prediction|予測/ });
    await predictionDialog.waitFor({ state: "visible" });
    await predictionDialog.screenshot({ path: path.join(outputDir, "leaderboard_prediction_modal.png") });
    await predictionDialog.getByRole("button", { name: /Close|閉じる/ }).first().click();
    await predictionDialog.waitFor({ state: "hidden" });
    await page.screenshot({ path: path.join(outputDir, "0121_i6_leaderboard_pilot.png"), fullPage: true });

    const evidence = {
      schema_version: "tablex_browser_smoke_result.v1",
      project_id: project.id,
      upload_job_id: completedUpload.id,
      upload_primary_dataset_snapshot_id_after_upload: null,
      seed,
      prediction_job_id: predictionJob.id,
      frontend_base: frontendBase,
      backend_base: backendBase,
      screenshots: [
        "output/playwright/0121_i6_notebook_from_chat.png",
        "output/playwright/0121_i6_notebook_from_leaderboard.png",
        "output/playwright/0121_i6_leaderboard_pilot.png",
        "output/playwright/leaderboard_prediction_modal.png",
      ],
    };
    await writeFile(path.join(outputDir, "0121_i6_golden_slice_result.json"), `${JSON.stringify(evidence, null, 2)}\n`, "utf-8");
    console.log(JSON.stringify(evidence, null, 2));
  } finally {
    if (api) await api.dispose();
    if (browser) await browser.close();
    await frontend.stop();
    await backend.stop();
  }
}

main()
  .then(() => {
    process.exit(0);
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
