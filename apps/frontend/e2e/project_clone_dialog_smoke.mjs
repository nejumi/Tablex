import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const baseUrl = process.env.TABLEX_BASE_URL ?? "http://127.0.0.1:8080";
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const outputDir =
  process.env.TABLEX_SCREENSHOT_DIR ?? path.resolve(scriptDir, "../../../docs/evidence/playwright");

await fs.mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: process.env.PLAYWRIGHT_HEADLESS !== "0" });

try {
  for (const [label, viewport] of [
    ["desktop", { width: 1440, height: 1000 }],
    ["mobile", { width: 390, height: 844 }]
  ]) {
    const page = await browser.newPage({ viewport });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.locator("button.project-clone-button").first().click();
    const dialog = page.locator(".project-clone-dialog");
    await dialog.waitFor();
    const metrics = await dialog.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      const overflowing = [...element.querySelectorAll("*")].filter(
        (node) => node.scrollWidth > node.clientWidth + 1
      );
      return {
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        overflowing: overflowing.length
      };
    });
    if (metrics.overflowing > 0 || metrics.rect.x < 0 || metrics.rect.width > viewport.width) {
      throw new Error(`${label} clone dialog does not fit: ${JSON.stringify(metrics)}`);
    }
    await page.screenshot({
      path: path.join(outputDir, `project-clone-dialog-${label}.png`),
      fullPage: true
    });
    console.log(`${label}: ${JSON.stringify(metrics)}`);
    await page.close();
  }
} finally {
  await browser.close();
}
