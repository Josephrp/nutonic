/**
 * PM2 process definitions for NU:TONIC monorepo verification threads.
 *
 * Logs are written under ./logs (gitignored). Start one app at a time unless
 * you accept multiple Gradle daemons competing for CPU/disk:
 *
 *   npx pm2 start ecosystem.config.cjs --only nutonic-test
 *   npm run pm2:test
 *
 * @see rules/11-vscode-testing-linting-and-ci.md
 * @see rules/14-testing-validation-pm2-and-documentation.md
 */
const path = require("path");

const repoRoot = __dirname;
const log = (...segs) => path.join(repoRoot, "logs", ...segs);

const gradleRunner = {
  script: path.join(repoRoot, "scripts", "pm2-run-gradle.cjs"),
  cwd: repoRoot,
  interpreter: "node",
  // One-shot Gradle tasks should not respawn on exit (success or failure).
  autorestart: false,
  max_restarts: 0,
  time: true,
};

module.exports = {
  apps: [
    {
      ...gradleRunner,
      name: "nutonic-test",
      args: ["--no-configuration-cache", "test"],
      out_file: log("nutonic-test.out.log"),
      error_file: log("nutonic-test.err.log"),
      merge_logs: true,
    },
    {
      ...gradleRunner,
      name: "nutonic-quality",
      args: ["--no-configuration-cache", "quality"],
      out_file: log("nutonic-quality.out.log"),
      error_file: log("nutonic-quality.err.log"),
      merge_logs: true,
    },
    {
      ...gradleRunner,
      name: "nutonic-ci-local",
      args: ["--no-configuration-cache", "--continue", "quality", "test"],
      out_file: log("nutonic-ci-local.out.log"),
      error_file: log("nutonic-ci-local.err.log"),
      merge_logs: true,
    },
    {
      ...gradleRunner,
      name: "nutonic-build-verify",
      args: [
        "--no-configuration-cache",
        "test",
        ":androidApp:assembleDebug",
        ":desktopApp:compileKotlinJvm",
        ":webApp:jsBrowserProductionWebpack",
        ":webApp:wasmJsBrowserProductionWebpack",
      ],
      out_file: log("nutonic-build-verify.out.log"),
      error_file: log("nutonic-build-verify.err.log"),
      merge_logs: true,
    },
    {
      ...gradleRunner,
      name: "nutonic-test-watch",
      args: ["--no-configuration-cache", "test", "--continuous"],
      // Long-running: restart if the watcher process crashes.
      autorestart: true,
      max_restarts: 10,
      min_uptime: "10s",
      out_file: log("nutonic-test-watch.out.log"),
      error_file: log("nutonic-test-watch.err.log"),
      merge_logs: true,
    },
  ],
};
