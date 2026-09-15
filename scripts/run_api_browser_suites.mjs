import { spawn } from "node:child_process";
import { mkdir, readdir, writeFile } from "node:fs/promises";
import { constants } from "node:os";
import { dirname, isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const webDirectory = join(root, "apps", "web");
const specDirectory = join(root, "tests", "e2e", "api-web");
const projects = [
  "api-chromium-desktop",
  "api-chromium-tablet",
  "api-chromium-mobile",
];
const listOnly = process.argv.length === 3 && process.argv[2] === "--list";
if (process.argv.length > 2 && !listOnly) {
  console.error("Usage: node scripts/run_api_browser_suites.mjs [--list]");
  process.exit(2);
}

const evidenceDirectory = process.env.T212PI_E2E_EVIDENCE_DIR;
if (evidenceDirectory && !isAbsolute(evidenceDirectory)) {
  throw new Error(
    "T212PI_E2E_EVIDENCE_DIR must be an absolute output directory.",
  );
}

let activeChild;
let interruptedSignal;
const grouped = process.platform !== "win32";
function interrupt(signal) {
  interruptedSignal ??= signal;
  if (activeChild?.pid && activeChild.exitCode === null) {
    try {
      if (grouped) process.kill(-activeChild.pid, signal);
      else activeChild.kill(signal);
    } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
  }
}
const onInterrupt = () => interrupt("SIGINT");
const onTerminate = () => interrupt("SIGTERM");
process.on("SIGINT", onInterrupt);
process.on("SIGTERM", onTerminate);

function run(arguments_, fixture, reportPath) {
  return new Promise((resolve, reject) => {
    const environment = { ...process.env };
    if (reportPath) {
      // The CLI selects both reporters; an inherited override must not suppress JSON.
      delete environment.PW_TEST_REPORTER;
      environment.PLAYWRIGHT_JSON_OUTPUT_NAME = reportPath;
    }
    activeChild = spawn("corepack", arguments_, {
      cwd: webDirectory,
      env: {
        ...environment,
        // Each process still gets a fresh database and the production quota.
        // Each intelligence suite loads only its own deterministic source fixture.
        T212PI_E2E_HISTORICAL: [
          "historical.spec.ts",
          "workspace.spec.ts",
          "intelligence.spec.ts",
        ].includes(fixture)
          ? "1"
          : "0",
        T212PI_E2E_RISK: ["risk.spec.ts", "premium-reports.spec.ts"].includes(
          fixture,
        )
          ? "1"
          : "0",
        T212PI_E2E_PROJECTIONS: [
          "projections.spec.ts",
          "projection-reports.spec.ts",
        ].includes(fixture)
          ? "1"
          : "0",
        T212PI_E2E_XRAY: ["xray.spec.ts", "research.spec.ts"].includes(fixture)
          ? "1"
          : "0",
        T212PI_E2E_RESEARCH: fixture === "research.spec.ts" ? "1" : "0",
        T212PI_E2E_SCENARIOS: [
          "scenarios.spec.ts",
          "scenario-reports.spec.ts",
        ].includes(fixture)
          ? "1"
          : "0",
        T212PI_E2E_REPORTS: [
          "reports.spec.ts",
          "premium-reports.spec.ts",
          "scenario-reports.spec.ts",
          "projection-reports.spec.ts",
        ].includes(fixture)
          ? "1"
          : "0",
        T212PI_E2E_ALERTS: fixture === "alerts.spec.ts" ? "1" : "0",
      },
      stdio: "inherit",
      shell: false,
      detached: grouped,
    });
    activeChild.once("error", reject);
    activeChild.once("close", (code, signal) => {
      activeChild = undefined;
      resolve(code ?? 128 + (constants.signals[signal] ?? 1));
    });
  });
}

try {
  const specs = (await readdir(specDirectory, { withFileTypes: true }))
    .filter((entry) => entry.isFile() && entry.name.endsWith(".spec.ts"))
    .map((entry) => entry.name)
    .sort();
  if (!specs.length) throw new Error("No API browser spec files were found.");
  suiteLoop: for (const spec of specs) {
    // Playwright treats file arguments as regular expressions. Anchor the exact
    // discovered basename so another spec cannot share this fixture lifecycle.
    const fileFilter = `(?:^|[\\\\/])${spec.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`;
    // Every feature workflow exercises all supported widths, one process and
    // one disposable database at a time against the same PostgreSQL container.
    for (const project of projects) {
      if (interruptedSignal) break suiteLoop;
      let reportPath;
      if (evidenceDirectory && !listOnly) {
        await mkdir(evidenceDirectory, { recursive: true });
        reportPath = join(evidenceDirectory, spec + "-" + project + ".json");
        // Reserve a unique output; repeated verification must use a fresh directory.
        await writeFile(reportPath, "", { flag: "wx", mode: 0o600 });
      }
      console.log(`API browser suite: ${spec} · ${project}`);
      const code = await run(
        [
          "pnpm",
          "exec",
          "playwright",
          "test",
          "--config=playwright.api.config.ts",
          `--project=${project}`,
          ...(listOnly ? ["--list"] : []),
          ...(reportPath ? ["--reporter=list,json"] : []),
          fileFilter,
        ],
        spec,
        reportPath,
      );
      if (code !== 0) {
        process.exitCode = code;
        break suiteLoop;
      }
    }
  }
  if (interruptedSignal)
    process.exitCode = 128 + constants.signals[interruptedSignal];
} catch (error) {
  console.error(`API browser suite runner failed: ${error.message}`);
  process.exitCode = 1;
} finally {
  process.off("SIGINT", onInterrupt);
  process.off("SIGTERM", onTerminate);
}
