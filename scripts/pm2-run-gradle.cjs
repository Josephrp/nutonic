#!/usr/bin/env node
/**
 * Cross-platform Gradle wrapper launcher for PM2 (repo root → nutonic/gradlew).
 * Stdout/stderr flow to the Node process so PM2 captures them into logs/*.log.
 */
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const repoRoot = path.resolve(__dirname, "..");
const nutonicDir = path.join(repoRoot, "nutonic");

fs.mkdirSync(path.join(repoRoot, "logs"), { recursive: true });
const isWin = process.platform === "win32";
const gradlew = isWin
  ? path.join(nutonicDir, "gradlew.bat")
  : path.join(nutonicDir, "gradlew");

if (!fs.existsSync(gradlew)) {
  console.error("[pm2-run-gradle] Gradle wrapper not found:", gradlew);
  process.exit(1);
}

const args = process.argv.slice(2);
const child = spawn(gradlew, args, {
  cwd: nutonicDir,
  stdio: "inherit",
  shell: isWin,
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.exit(1);
  }
  process.exit(code === null ? 1 : code);
});

child.on("error", (err) => {
  console.error("[pm2-run-gradle]", err);
  process.exit(1);
});
