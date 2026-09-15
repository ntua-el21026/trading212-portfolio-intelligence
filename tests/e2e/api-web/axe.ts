import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { expect, type Page } from "@playwright/test";

// Reuse the exact axe version already frozen by eslint-config-next. No download
// or additional browser runtime is needed for this test instrumentation.
const root = createRequire(__filename);
const next = createRequire(root.resolve("eslint-config-next"));
const plugin = createRequire(next.resolve("eslint-plugin-jsx-a11y"));
const source = readFileSync(plugin.resolve("axe-core/axe.min.js"), "utf8");
type Finding = {
  id: string;
  impact: string | null;
  nodes: { target: string[] }[];
};
export async function assertAccessible(page: Page) {
  // DevTools instrumentation executes the installed auditor without weakening
  // the application's CSP or adding a script to its public/offline cache.
  await page.evaluate(source);
  const findings = await page.evaluate(async () => {
    const auditor = (
      window as unknown as {
        axe: {
          run(options: object): Promise<{ violations: Finding[] }>;
        };
      }
    ).axe;
    const result = await auditor.run({
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
      },
    });
    return result.violations
      .filter((item) => item.impact === "serious" || item.impact === "critical")
      .map((item) => ({
        id: item.id,
        impact: item.impact,
        targets: item.nodes.map((node) => node.target),
      }));
  });
  expect(findings, "No serious/critical WCAG AA findings").toEqual([]);
}
