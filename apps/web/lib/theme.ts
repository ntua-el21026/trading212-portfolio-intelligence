/** Local visual preference only; never carries identity or portfolio data. */
export const THEME_COOKIE = "pi_theme_v1";
export type ThemePreference = "light" | "dark" | "system";

export function themePreference(value: unknown): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}
