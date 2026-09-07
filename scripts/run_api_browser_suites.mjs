import { spawn } from "node:child_process";
import { readdir } from "node:fs/promises";
import { constants } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const webDirectory = join(root, "apps", "web");
const specDirectory = join(root, "tests", "e2e", "api-web");
const projects = ["api-chromium-desktop", "api-chromium-mobile"];
const listOnly = process.argv.length === 3 && process.argv[2] === "--list";
if (process.argv.length > 2 && !listOnly) {
  console.error("Usage: node scripts/run_api_browser_suites.mjs [--list]");
  process.exit(2);
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

function run(arguments_) {
  return new Promise((resolve, reject) => {
    activeChild = spawn("corepack", arguments_, {
      cwd: webDirectory,
      env: process.env,
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
    for (const project of projects) {
      if (interruptedSignal) break suiteLoop;
      console.log(`API browser suite: ${spec} · ${project}`);
      const code = await run([
        "pnpm",
        "exec",
        "playwright",
        "test",
        "--config=playwright.api.config.ts",
        `--project=${project}`,
        ...(listOnly ? ["--list"] : []),
        fileFilter,
      ]);
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
