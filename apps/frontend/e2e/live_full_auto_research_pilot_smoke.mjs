#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const repoRoot = path.resolve(new URL("../../..", import.meta.url).pathname);
const outputDir = path.join(repoRoot, "output", "live");
const defaultResearchTimeoutMs = 20 * 60 * 1000;
const defaultAuditTimeoutMs = 25 * 60 * 1000;

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

function timestampSlug() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "Z");
}

function timeoutFromEnv(name, fallback) {
  const raw = Number.parseInt(process.env[name] || "", 10);
  return Number.isFinite(raw) && raw > 0 ? raw : fallback;
}

async function delay(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
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
    await delay(500);
  }
  throw new Error(`Timed out waiting for ${label}: ${lastError}`);
}

async function apiJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${options.method || "GET"} ${url} failed: ${response.status} ${await response.text()}`);
  return response.json();
}

async function waitForJob(apiBase, jobId, { timeoutMs = 120_000 } = {}) {
  const start = Date.now();
  let latest = null;
  while (Date.now() - start < timeoutMs) {
    latest = await apiJson(`${apiBase}/api/jobs/${jobId}`);
    if (latest.status === "succeeded") return latest;
    if (latest.status === "failed" || latest.status === "cancelled") {
      throw new Error(`Job ${jobId} ended with ${latest.status}: ${JSON.stringify(latest.output ?? latest.failure_reason ?? latest.error_message)}`);
    }
    await delay(700);
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
  const project = await apiJson(`${apiBase}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: "0121 live research pilot smoke",
      description: "Live Full Auto audit smoke for source-backed research and pilot observation.",
      target_column: "converted",
      task_type: "binary_classification",
    }),
  });
  const rows = [
    "customer_id,age,balance,contact_count,previous_campaign_success,channel,converted",
    "C001,44,6200,2,1,email,1",
    "C002,29,300,1,0,phone,0",
    "C003,52,7800,3,1,email,1",
    "C004,36,1500,2,0,phone,0",
    "C005,61,9100,1,1,email,1",
    "C006,24,450,5,0,phone,0",
    "C007,48,5300,4,0,email,1",
    "C008,33,800,2,0,phone,0",
    "C009,57,7200,1,1,email,1",
    "C010,41,2200,3,0,email,0",
    "C011,39,3600,2,1,phone,1",
    "C012,27,500,4,0,phone,0",
  ];
  const form = new FormData();
  form.append("files", new Blob([`${rows.join("\n")}\n`], { type: "text/csv" }), "bank_marketing_live.csv");
  form.append("primary_filename", "bank_marketing_live.csv");
  form.append("target_column", "converted");
  const uploadJob = await apiJson(`${apiBase}/api/projects/${project.id}/datasets/upload-bundle`, {
    method: "POST",
    body: form,
  });
  await fetch(`${apiBase}/api/jobs/${uploadJob.id}/run`, { method: "POST" });
  const completedUpload = await waitForJob(apiBase, uploadJob.id, { timeoutMs: 120_000 });
  return { project, completedUpload };
}

async function startFullAuto(apiBase, projectId) {
  return apiJson(`${apiBase}/api/projects/${projectId}/autonomy/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ runner_mode: "codex_cli", autonomy_mode: "full_auto", locale: "en-US" }),
  });
}

async function sendLiveInstruction(apiBase, projectId, message) {
  return apiJson(`${apiBase}/api/projects/${projectId}/agent-chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, locale: "en-US" }),
  });
}

async function artifactPayload(apiBase, artifactId) {
  const response = await fetch(`${apiBase}/api/artifacts/${artifactId}/download`);
  if (!response.ok) throw new Error(`Artifact download failed: ${artifactId} ${response.status}`);
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function artifactsByType(apiBase, projectId, assetType) {
  return apiJson(`${apiBase}/api/projects/${projectId}/artifacts?asset_type=${encodeURIComponent(assetType)}&limit=200`);
}

async function transcriptSummary(apiBase, projectId) {
  const events = await apiJson(`${apiBase}/api/projects/${projectId}/agent-session/transcript?limit=1000`);
  const current = await apiJson(`${apiBase}/api/projects/${projectId}/agent-session/current`);
  return {
    session: current,
    event_count: events.length,
    stdout_count: events.filter((event) => event.source === "codex_cli").length,
    stderr_count: events.filter((event) => event.source === "codex_cli_stderr").length,
    last_events: events.slice(-8).map((event) => ({
      event_index: event.event_index,
      source: event.source,
      event_type: event.event_type,
      title: event.title,
      content: String(event.content || "").slice(0, 300),
    })),
  };
}

async function waitForResearch(apiBase, projectId, timeoutMs) {
  const start = Date.now();
  let latest = [];
  while (Date.now() - start < timeoutMs) {
    latest = await artifactsByType(apiBase, projectId, "research_findings_report");
    for (const artifact of latest) {
      const payload = await artifactPayload(apiBase, artifact.id);
      if (
        payload &&
        typeof payload === "object" &&
        Array.isArray(payload.sources) &&
        payload.sources.length > 0 &&
        Array.isArray(payload.findings) &&
        payload.findings.length > 0 &&
        typeof payload.rich_report_artifact_id === "string" &&
        payload.rich_report_artifact_id
      ) {
        return {
          artifact,
          source_count: payload.sources.length,
          finding_count: payload.findings.length,
          rich_report_artifact_id: payload.rich_report_artifact_id,
          figure_artifact_ids: Array.isArray(payload.figure_artifact_ids) ? payload.figure_artifact_ids : [],
        };
      }
    }
    await delay(5000);
  }
  throw new Error(`Timed out waiting for source-backed research findings; latest count=${latest.length}`);
}

function runPilotSeed(env, projectId) {
  const completed = spawnSync(
    path.join(repoRoot, ".venv", "bin", "python"),
    [path.join(repoRoot, "apps", "frontend", "e2e", "seed_live_pilot_materials.py"), "--project-id", projectId],
    { cwd: repoRoot, env, encoding: "utf-8" },
  );
  if (completed.status !== 0) {
    throw new Error(`Pilot seed failed:\n${completed.stdout}\n${completed.stderr}`);
  }
  return JSON.parse(completed.stdout.trim().split(/\n/).filter(Boolean).join("\n"));
}

async function runPilotLoop(apiBase, projectId, seed) {
  const deployment = await apiJson(`${apiBase}/api/projects/${projectId}/pilot-deployments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pipeline_artifact_id: seed.pipeline_artifact_id,
      experiment_run_id: seed.experiment_run_id,
      model_version_id: seed.model_version_id,
      notes: "Live audit pilot deployment.",
    }),
  });
  const predictionJob = await apiJson(`${apiBase}/api/pilot-deployments/${deployment.id}/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      dataset_snapshot_id: seed.future_dataset_snapshot_id,
      as_of: "2026-07-09T00:00:00Z",
      timeout_seconds: 120,
    }),
  });
  await fetch(`${apiBase}/api/jobs/${predictionJob.id}/run`, { method: "POST" });
  const prediction = await waitForJob(apiBase, predictionJob.id, { timeoutMs: 180_000 });
  const predictionBatchId = prediction.output?.pilot_prediction_batch_id;
  if (!predictionBatchId) throw new Error(`Prediction job did not create a pilot batch: ${JSON.stringify(prediction.output)}`);

  const outcomeJob = await apiJson(`${apiBase}/api/pilot-deployments/${deployment.id}/outcomes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      outcomes_artifact_id: seed.outcomes_artifact_id,
      prediction_batch_id: predictionBatchId,
      join_keys: ["customer_id"],
      actual_column: "converted",
      prediction_column: "prediction",
      observed_at_column: "observed_at",
    }),
  });
  await fetch(`${apiBase}/api/jobs/${outcomeJob.id}/run`, { method: "POST" });
  const scoring = await waitForJob(apiBase, outcomeJob.id, { timeoutMs: 180_000 });
  return { deployment, prediction, scoring };
}

async function waitForValidationAudit(apiBase, projectId, deploymentId, scoringReportArtifactId, timeoutMs) {
  const start = Date.now();
  let latest = [];
  while (Date.now() - start < timeoutMs) {
    latest = await artifactsByType(apiBase, projectId, "validation_scheme_audit");
    for (const artifact of latest) {
      const payload = await artifactPayload(apiBase, artifact.id);
      if (
        payload &&
        typeof payload === "object" &&
        payload.deployment_id === deploymentId &&
        (payload.pilot_scoring_report_artifact_id === scoringReportArtifactId ||
          (Array.isArray(payload.scoring_report_artifact_ids) &&
            payload.scoring_report_artifact_ids.includes(scoringReportArtifactId)))
      ) {
        return { artifact, scheme_verdict: payload.scheme_verdict, next_iteration_focus: payload.next_iteration_focus };
      }
    }
    await delay(5000);
  }
  throw new Error(`Timed out waiting for validation audit; latest count=${latest.length}`);
}

async function stopFullAuto(apiBase, projectId) {
  try {
    return await apiJson(`${apiBase}/api/projects/${projectId}/autonomy/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locale: "en-US" }),
    });
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const evidenceSlug = timestampSlug();
  const backendPort = await freePort();
  const tempRoot = await fsMkdtemp(path.join(os.tmpdir(), "tablex-live-i6-"));
  const dataDir = path.join(tempRoot, "data");
  const backendBase = `http://127.0.0.1:${backendPort}`;
  const env = {
    ...process.env,
    PYTHONPATH: path.join(repoRoot, "apps", "backend"),
    HARNESS_DATA_DIR: dataDir,
    HARNESS_ARTIFACT_ROOT: path.join(dataDir, "artifacts"),
    HARNESS_DATABASE_URL: `sqlite:///${path.join(dataDir, "metadata", "app.db")}`,
    HARNESS_CORS_ORIGINS: "http://127.0.0.1:5173",
    TABLEX_AUTH_ENABLED: "false",
    TABLEX_API_AGENT_SESSION_SUPERVISOR_ENABLED: "true",
    TABLEX_LOCAL_WORKER_ENABLED: "true",
    TABLEX_LOCAL_WORKER_INTERVAL_SECONDS: "0.2",
    TABLEX_AGENT_SESSION_NETWORK_ENABLED: "true",
    TABLEX_AGENT_SESSION_WEB_SEARCH_ENABLED: "true",
  };
  const backend = startProcess(
    path.join(repoRoot, ".venv", "bin", "python"),
    ["-m", "uvicorn", "tabular_harness.main:app", "--app-dir", "apps/backend", "--host", "127.0.0.1", "--port", String(backendPort)],
    { env, label: "backend" },
  );

  const evidencePath = path.join(outputDir, `0121_i6_live_full_auto_research_pilot_${evidenceSlug}.json`);
  const partial = { schema_version: "tablex_live_full_auto_i6_smoke.v1", evidence_slug: evidenceSlug, backend_base: backendBase };
  try {
    await waitForHttp(`${backendBase}/health`, { label: "backend health" });
    const { project, completedUpload } = await createProjectAndUpload(backendBase);
    partial.project_id = project.id;
    partial.upload_job_id = completedUpload.id;

    const startJob = await startFullAuto(backendBase, project.id);
    partial.start_job_id = startJob.id;
    partial.agent_session_id = startJob.output?.agent_session_id;
    await sendLiveInstruction(
      backendBase,
      project.id,
      [
        "For this audit smoke, prioritize one source-backed prior-knowledge research pass for the uploaded conversion dataset.",
        "Use live web search if available, save a concise Markdown report, and register tablex_research_request.v1 findings with sources.",
        "When a pilot observation appears later, read it and register tablex_pilot_request.v1 validation audit.",
      ].join(" "),
    );

    const research = await waitForResearch(
      backendBase,
      project.id,
      timeoutFromEnv("TABLEX_LIVE_RESEARCH_TIMEOUT_MS", defaultResearchTimeoutMs),
    );
    partial.research = research;

    const seed = runPilotSeed(env, project.id);
    partial.pilot_seed = seed;
    const pilot = await runPilotLoop(backendBase, project.id, seed);
    partial.pilot = {
      deployment_id: pilot.deployment.id,
      prediction_job_id: pilot.prediction.id,
      prediction_batch_id: pilot.prediction.output?.pilot_prediction_batch_id,
      scoring_job_id: pilot.scoring.id,
      scoring_report_artifact_id: pilot.scoring.output?.pilot_scoring_report_artifact_id,
      notified_agent_session_id: pilot.scoring.output?.notified_agent_session_id,
      session_continuation_job_id: pilot.scoring.output?.session_continuation_job_id,
      metrics: pilot.scoring.output?.metrics,
    };
    await sendLiveInstruction(
      backendBase,
      project.id,
      "A pilot scoring observation is now available. Read the pilot observation from the inbox and register the validation audit request before doing additional modeling.",
    );
    const audit = await waitForValidationAudit(
      backendBase,
      project.id,
      pilot.deployment.id,
      pilot.scoring.output?.pilot_scoring_report_artifact_id,
      timeoutFromEnv("TABLEX_LIVE_AUDIT_TIMEOUT_MS", defaultAuditTimeoutMs),
    );
    partial.validation_audit = audit;
    partial.transcript = await transcriptSummary(backendBase, project.id);
    partial.stop = await stopFullAuto(backendBase, project.id);
    partial.status = "passed";
    await writeFile(evidencePath, `${JSON.stringify(partial, null, 2)}\n`, "utf-8");
    console.log(JSON.stringify(partial, null, 2));
  } catch (error) {
    partial.status = "failed";
    partial.error = error instanceof Error ? error.stack || error.message : String(error);
    if (partial.project_id) {
      partial.transcript = await transcriptSummary(backendBase, partial.project_id).catch((summaryError) => ({
        error: summaryError instanceof Error ? summaryError.message : String(summaryError),
      }));
      partial.stop = await stopFullAuto(backendBase, partial.project_id);
    }
    await writeFile(evidencePath, `${JSON.stringify(partial, null, 2)}\n`, "utf-8");
    throw error;
  } finally {
    await backend.stop();
  }
}

async function fsMkdtemp(prefix) {
  const { mkdtemp } = await import("node:fs/promises");
  return mkdtemp(prefix);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
