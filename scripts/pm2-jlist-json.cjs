#!/usr/bin/env node
/**
 * Print PM2 `jlist` as a single JSON array to stdout.
 * Strips leading banner lines (e.g. version mismatch) so output is safe for `JSON.parse`.
 */
const { execSync } = require("child_process");

const raw = execSync("npx pm2 jlist", { encoding: "utf8", shell: true });
const start = raw.indexOf("[");
if (start === -1) {
  console.error("[pm2-jlist-json] No JSON array found in pm2 jlist output.");
  process.exit(1);
}
process.stdout.write(raw.slice(start).trimEnd());
