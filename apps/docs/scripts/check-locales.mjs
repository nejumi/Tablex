import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const docsDir = join(root, "docs");
const locales = ["ja", "zh-Hans", "ko"];

function walk(dir) {
  const entries = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      entries.push(...walk(full));
    } else if (name.endsWith(".md") || name.endsWith(".mdx")) {
      entries.push(full);
    }
  }
  return entries;
}

const sourceDocs = walk(docsDir).map((file) => relative(docsDir, file));
const missing = [];

for (const locale of locales) {
  const localeRoot = join(root, "i18n", locale, "docusaurus-plugin-content-docs", "current");
  for (const doc of sourceDocs) {
    try {
      statSync(join(localeRoot, doc));
    } catch {
      missing.push(`${locale}:${doc}`);
    }
  }
}

if (missing.length) {
  console.error("Missing localized docs:");
  for (const item of missing) console.error(`- ${item}`);
  process.exit(1);
}

console.log(`All ${sourceDocs.length} canonical docs are localized for ${locales.join(", ")}.`);
