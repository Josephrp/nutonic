#!/usr/bin/env node
/**
 * Poll PM2 until the named app is no longer "online" (or timeout).
 * Uses pm2-jlist-json to avoid PowerShell JSON duplicate-key issues and jlist banners.
 *
 * Usage: node scripts/pm2-wait-until-stopped.cjs <app-name> [timeout-ms]
 * Exit: 0 if app left "online" within timeout, 1 on timeout or error.
 */
const { execSync } = require("child_process");
const path = require("path");
const { setTimeout: delay } = require("timers/promises");

const appName = process.argv[2];
const timeoutMs = parseInt(process.argv[3] || String(60 * 60 * 1000), 10);
const pollMs = 5000;

if (!appName) {
  console.error("Usage: node pm2-wait-until-stopped.cjs <app-name> [timeout-ms]");
  process.exit(1);
}

const jlistScript = path.join(__dirname, "pm2-jlist-json.cjs");

function listApps() {
  const out = execSync(`node "${jlistScript}"`, { encoding: "utf8", shell: true });
  return JSON.parse(out);
}

async function main() {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    let apps;
    try {
      apps = listApps();
    } catch (e) {
      console.error("[pm2-wait-until-stopped] jlist parse failed:", e.message);
      process.exit(1);
    }

    const app = apps.find((a) => a.name === appName);
    if (!app) {
      console.error(`[pm2-wait-until-stopped] App "${appName}" not found in PM2 list.`);
      process.exit(1);
    }

    const status = app.pm2_env && app.pm2_env.status;
    process.stderr.write(`[pm2-wait-until-stopped] ${appName} status=${status}\n`);

    if (status !== "online") {
      process.exit(0);
    }

    await delay(Math.min(pollMs, Math.max(0, deadline - Date.now())));
  }

  console.error(`[pm2-wait-until-stopped] Timeout waiting for ${appName} to finish.`);
  process.exit(1);
}

main();
