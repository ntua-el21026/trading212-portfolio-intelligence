import { expect, type Page } from "@playwright/test";

export async function keyboardClearance(page: Page) {
  async function inspectFocusedControl() {
    return page.evaluate(() => {
      const active = document.activeElement;
      if (
        !(active instanceof HTMLElement) ||
        !active.closest("main") ||
        active.tagName === "MAIN"
      )
        return null;
      const box = active.getBoundingClientRect();
      if (!box.width || !box.height) return null;
      const header = document
        .querySelector("header.topbar")
        ?.getBoundingClientRect();
      const navigation =
        document.querySelector<HTMLElement>(".mobile-navigation");
      const bottom =
        navigation && getComputedStyle(navigation).display !== "none"
          ? navigation.getBoundingClientRect().top
          : innerHeight;
      const style = getComputedStyle(active);
      return {
        focusVisible:
          style.outlineStyle !== "none" &&
          Number.parseFloat(style.outlineWidth) >= 2,
        name:
          active.getAttribute("aria-label") ||
          (active instanceof HTMLInputElement &&
            active.labels?.[0]?.textContent?.trim()) ||
          active.textContent?.slice(0, 80) ||
          active.tagName,
        geometry: {
          top: box.top,
          bottom: box.bottom,
          left: box.left,
          right: box.right,
          headerBottom: header?.bottom ?? 0,
          navigationTop: bottom,
          viewportWidth: innerWidth,
          scrollY,
        },
        clear:
          box.top >= (header?.bottom ?? 0) - 1 &&
          box.bottom <= bottom + 1 &&
          box.left >= -1 &&
          box.right <= innerWidth + 1,
      };
    });
  }
  for (const [key, steps] of [
    ["Tab", 55],
    ["Shift+Tab", 55],
  ] as const) {
    let measured = 0;
    for (let step = 0; step < steps; step += 1) {
      await page.keyboard.press(key);
      const result = await inspectFocusedControl();
      if (result) {
        measured += 1;
        expect(
          result.focusVisible,
          "Visible keyboard focus: " + result.name,
        ).toBe(true);
        // Native keyboard scrolling may animate. Observe its settled result;
        // never move focus or scroll the page on behalf of the implementation.
        await expect
          .poll(inspectFocusedControl, {
            timeout: 1_500,
            message:
              "Focus visible after " +
              key +
              " without scroll rescue: " +
              result.name,
          })
          .toMatchObject({ clear: true, focusVisible: true })
          .catch(async (error: unknown) => {
            throw new Error(
              "Settled focus geometry: " +
                JSON.stringify(await inspectFocusedControl()),
              { cause: error },
            );
          });
      }
    }
    expect(
      measured,
      "At least one main control reached with " + key,
    ).toBeGreaterThan(0);
  }
}
