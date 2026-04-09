#!/usr/bin/env node
/**
 * Delete NU:TONIC PM2 app names that are currently registered (no ERROR spam for missing names).
 */
const { execSync } = require("child_process");
const path = require("path");

const names = new Set([
  "nutonic-test",
  "nutonic-quality",
  "nutonic-ci-local",
  "nutonic-build-verify",
  "nutonic-test-watch",
]);

const jlistScript = path.join(__dirname, "pm2-jlist-json.cjs");

let apps;
try {
  const out = execSync(`node "${jlistScript}"`, { encoding: "utf8", shell: true });
  apps = JSON.parse(out);
} catch (e) {
  console.error("[pm2-stop-nutonic] Could not list PM2 apps:", e.message);
  process.exit(1);
}

const toDelete = apps.filter((a) => names.has(a.name));
for (const a of toDelete) {
  try {
    execSync(`npx pm2 delete ${a.name}`, {
      stdio: "inherit",
      shell: true,
      windowsHide: true,
    });
  } catch {
    /* ignore */
  }
}

if (toDelete.length === 0) {
  process.stderr.write("[pm2-stop-nutonic] No nutonic-* PM2 apps were running.\n");
}
