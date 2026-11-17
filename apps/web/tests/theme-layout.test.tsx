import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_COOKIE } from "../lib/theme";

const request = vi.hoisted(() => ({ value: undefined as string | undefined }));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "pi_theme_v1" ? { value: request.value } : undefined,
  }),
}));
vi.mock("../components/pwa-runtime", () => ({ PwaRuntime: () => null }));
import RootLayout, { generateViewport } from "../app/layout";

beforeEach(() => {
  request.value = undefined;
});

describe("appearance before JavaScript and first paint", () => {
  it.each(["light", "dark", "system", undefined, "unexpected"])(
    "renders safe SSR preference for %s",
    async (value) => {
      request.value = value;
      const html = renderToStaticMarkup(
        await RootLayout({ children: <main>Public synthetic view</main> }),
      );
      expect(html).toContain(
        `data-theme="${value === "dark" || value === "light" ? value : "system"}"`,
      );
      expect(html).not.toContain("<script");
      expect(html).not.toContain(THEME_COOKIE);
      expect(html).toContain("Public synthetic view");
    },
  );

  it.each([
    ["light", "#fcfdfd"],
    ["dark", "#10171b"],
  ])(
    "sets first-paint browser chrome for saved %s independent of the OS",
    async (value, color) => {
      request.value = value;
      expect((await generateViewport()).themeColor).toBe(color);
    },
  );

  it("lets native CSS and viewport media resolve system preference without client warmup", async () => {
    expect((await generateViewport()).themeColor).toEqual([
      { media: "(prefers-color-scheme: light)", color: "#fcfdfd" },
      { media: "(prefers-color-scheme: dark)", color: "#10171b" },
    ]);
  });
});
