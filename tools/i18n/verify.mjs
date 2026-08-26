#!/usr/bin/env node
// i18n completeness check — `make verify-i18n` and the pre-commit hook both call this.
// Fails (exit 1) if any locale key exists in one of si/ta/en but not all three, in either:
//   - packages/ts-shared/src/i18n/locales/{si,ta,en}.json  (the shared catalogue)
//   - apps/*/messages/{si,ta,en}.json                       (per-app catalogues, once they exist)
//
// No dependencies on purpose — this has to run in CI and pre-commit with nothing but Node.

import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, "..", "..");
const LOCALES = ["si", "ta", "en"];

function collectKeyPaths(obj, prefix = "") {
  if (obj === null || typeof obj !== "object") return [prefix];
  return Object.entries(obj).flatMap(([key, value]) =>
    collectKeyPaths(value, prefix ? `${prefix}.${key}` : key),
  );
}

function checkCatalogue(label, dir) {
  const byLocale = {};
  for (const locale of LOCALES) {
    const path = join(dir, `${locale}.json`);
    if (!existsSync(path)) {
      byLocale[locale] = null; // whole file missing
      continue;
    }
    const data = JSON.parse(readFileSync(path, "utf-8"));
    byLocale[locale] = new Set(collectKeyPaths(data));
  }

  const presentLocales = LOCALES.filter((l) => byLocale[l] !== null);
  if (presentLocales.length === 0) {
    return { label, ok: true, note: "no locale files found, skipped" };
  }

  const allKeys = new Set(presentLocales.flatMap((l) => [...byLocale[l]]));
  const problems = [];

  for (const locale of LOCALES) {
    if (byLocale[locale] === null) {
      problems.push(`  ${locale}.json: file missing entirely`);
      continue;
    }
    const missing = [...allKeys].filter((k) => !byLocale[locale].has(k)).sort();
    if (missing.length > 0) {
      problems.push(`  ${locale}.json: missing ${missing.length} key(s): ${missing.join(", ")}`);
    }
  }

  return { label, ok: problems.length === 0, problems };
}

function findAppMessageDirs() {
  const appsDir = join(REPO_ROOT, "apps");
  if (!existsSync(appsDir)) return [];
  return readdirSync(appsDir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => join(appsDir, d.name, "messages"))
    .filter((p) => existsSync(p));
}

const targets = [
  ["packages/ts-shared/src/i18n/locales", join(REPO_ROOT, "packages/ts-shared/src/i18n/locales")],
  ...findAppMessageDirs().map((p) => [p.replace(REPO_ROOT + "/", ""), p]),
];

let failed = false;
for (const [label, dir] of targets) {
  const result = checkCatalogue(label, dir);
  if (result.note) {
    console.log(`⏭  ${label}: ${result.note}`);
    continue;
  }
  if (result.ok) {
    console.log(`✅ ${label}: complete across ${LOCALES.join("/")}`);
  } else {
    failed = true;
    console.error(`❌ ${label}:`);
    for (const p of result.problems) console.error(p);
  }
}

process.exit(failed ? 1 : 0);
