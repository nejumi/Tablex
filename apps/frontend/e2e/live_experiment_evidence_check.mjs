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
  await page.getByRole("button", { name: /^(Experiments|実験)$/ }).last().click();
  await page.getByText("Experiment Runs", { exact: true }).waitFor({ state: "visible" });
  await page.getByRole("columnheader", { name: "Evidence", exact: true }).waitFor({ state: "visible" });
  const missingEvidenceCount = await page.getByText("Not registered", { exact: true }).count();
  if (missingEvidenceCount < 1) {
    throw new Error("Existing exploratory runs were not preserved as evidence-unregistered rows");
  }
  await page.screenshot({ path: "/output/experiment_evidence_live.png", fullPage: false });
  process.stdout.write(`${JSON.stringify({ status: "passed", missingEvidenceCount })}\n`);
} finally {
  await browser.close();
}
