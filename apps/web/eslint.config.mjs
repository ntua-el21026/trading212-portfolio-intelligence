import { defineConfig, globalIgnores } from "eslint/config";
import eslint from "@eslint/js";
import nextPlugin from "@next/eslint-plugin-next";
import nextTypeScript from "eslint-config-next/typescript";
import reactHooks from "eslint-plugin-react-hooks";

export default defineConfig([
  eslint.configs.recommended,
  ...nextTypeScript,
  {
    plugins: {
      "@next/next": nextPlugin,
      "react-hooks": reactHooks,
    },
    rules: {
      ...nextPlugin.configs["core-web-vitals"].rules,
      ...reactHooks.configs.flat.recommended.rules,
    },
  },
  globalIgnores([
    ".next/**",
    "coverage/**",
    "playwright-report/**",
    "test-results/**",
  ]),
]);
