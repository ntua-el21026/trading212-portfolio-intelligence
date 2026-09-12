# ruff: noqa: E501
"""Versioned, dependency-free portfolio snapshot MCP Apps resource."""

from __future__ import annotations

import base64
import hashlib

SNAPSHOT_WIDGET_URI = "ui://trading212-portfolio/snapshot-v1.html"
SNAPSHOT_WIDGET_MIME = "text/html;profile=mcp-app"

SNAPSHOT_WIDGET_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Portfolio snapshot</title>
  <style>
    :root {
      color-scheme: light dark;
      --ink: #17211b;
      --muted: #68736d;
      --surface: #f7f8f4;
      --panel: #ffffff;
      --line: #dfe4dc;
      --accent: #145f45;
      --soft: #e8f2ec;
      --warning: #805d13;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --ink: #edf3ee;
        --muted: #aab7af;
        --surface: #111713;
        --panel: #18211b;
        --line: #344239;
        --accent: #83d7ad;
        --soft: #203b2f;
        --warning: #e5c267;
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 12px;
      color: var(--ink);
      background: var(--surface);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-variant-numeric: tabular-nums;
    }
    .card {
      width: min(100%, 760px);
      margin: 0 auto;
      padding: clamp(16px, 3vw, 24px);
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--panel);
      box-shadow: 0 10px 30px rgba(17, 35, 25, 0.06);
    }
    header { display: flex; gap: 12px; align-items: flex-start; justify-content: space-between; }
    h1 { margin: 0; font-size: clamp(18px, 3vw, 24px); letter-spacing: -0.025em; }
    .eyebrow { margin: 0 0 5px; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; }
    .badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
    .badge { padding: 5px 8px; border-radius: 999px; background: var(--soft); color: var(--accent); font-size: 12px; font-weight: 650; white-space: nowrap; }
    .badge[data-state="stale"], .badge[data-state="partial"], .badge[data-state="unreconciled"], .badge[data-state="failed"] { color: var(--warning); }
    .hero { margin: 22px 0 16px; }
    .hero-label { color: var(--muted); font-size: 13px; }
    .hero-value { overflow-wrap: anywhere; margin-top: 3px; font-size: clamp(30px, 8vw, 46px); line-height: 1.05; letter-spacing: -0.045em; font-weight: 720; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
    .metric { min-width: 0; padding: 12px; border: 1px solid var(--line); border-radius: 12px; }
    .metric dt { color: var(--muted); font-size: 12px; }
    .metric dd { margin: 5px 0 0; overflow-wrap: anywhere; font-size: 15px; font-weight: 650; }
    footer { margin-top: 16px; padding-top: 13px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; line-height: 1.45; }
    .disclosure { margin: 5px 0 0; }
    .empty { padding: 22px 0 8px; color: var(--muted); line-height: 1.5; }
    [hidden] { display: none !important; }
    @media (max-width: 560px) {
      header { display: block; }
      .badges { justify-content: flex-start; margin-top: 10px; }
      .grid { grid-template-columns: 1fr; }
    }
    @media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
  </style>
</head>
<body>
  <main class="card" aria-labelledby="title">
    <header>
      <div>
        <p class="eyebrow">Canonical observation</p>
        <h1 id="title">Portfolio snapshot</h1>
      </div>
      <div class="badges" aria-label="Snapshot disclosures">
        <span class="badge">Read-only</span>
        <span id="quality-badge" class="badge" hidden></span>
        <span id="synthetic-badge" class="badge" hidden>Synthetic data</span>
      </div>
    </header>

    <section id="empty" class="empty" aria-live="polite">
      Waiting for a portfolio snapshot. The conversation remains usable if this card cannot load.
    </section>

    <section id="content" hidden aria-live="polite">
      <div class="hero">
        <div class="hero-label">Total portfolio value</div>
        <div id="total-value" class="hero-value">—</div>
      </div>
      <dl class="grid">
        <div class="metric"><dt>Invested</dt><dd id="invested-value">—</dd></div>
        <div class="metric"><dt>Cash</dt><dd id="cash-value">—</dd></div>
        <div class="metric"><dt>Net contributions</dt><dd id="contributions-value">—</dd></div>
      </dl>
      <footer>
        <div id="as-of">As of —</div>
        <p id="quality-note" class="disclosure"></p>
        <p class="disclosure">Portfolio observations and deterministic analytics only. This app cannot place trades.</p>
      </footer>
    </section>
  </main>

  <script>
    (() => {
      "use strict";
      const byId = (id) => document.getElementById(id);
      const empty = byId("empty");
      const content = byId("content");
      const qualityBadge = byId("quality-badge");
      const syntheticBadge = byId("synthetic-badge");
      let rpcId = 0;
      let receivedToolNotification = false;
      const pending = new Map();

      const presentMoney = (metric, fallbackCurrency) => {
        if (!metric || metric.availability === "unavailable" || typeof metric.value !== "string") return "Unavailable";
        const currency = metric.reporting_currency ?? fallbackCurrency;
        const value = metric.value;
        // Phase 1 DecimalString does not impose the Phase 2 q18 wire restriction.
        // This is a display bound only; the structured tool result remains unchanged.
        if (value.length > 512) return "Value exceeds widget display limit; see the structured tool result.";
        if (!/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value) ||
            typeof currency !== "string" || !/^[A-Z]{3}$/.test(currency)) return "Unavailable";
        const reason = typeof metric.unavailable_reason === "string" && metric.unavailable_reason.length <= 240
          ? metric.unavailable_reason : "coverage detail unavailable";
        return `${value} ${currency}${metric.availability === "partial" ? ` (partial: ${reason})` : ""}`;
      };

      // Keep the exact source instant and explicit UTC/offset visible.
      const presentTime = (value) => typeof value === "string" && value.length <= 40 &&
        /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
          ? value : "Unavailable";

      const render = (envelope) => {
        qualityBadge.hidden = true;
        syntheticBadge.hidden = true;
        qualityBadge.textContent = "";
        delete qualityBadge.dataset.state;
        if (!envelope || envelope.error || !envelope.data || typeof envelope.data !== "object" || Array.isArray(envelope.data)) {
          empty.textContent = "Portfolio snapshot data is unavailable.";
          empty.hidden = false;
          content.hidden = true;
          return;
        }
        const data = envelope.data;
        const currency = envelope.reporting_currency || data.reporting_currency;
        byId("total-value").textContent = presentMoney(data.total_value, currency);
        byId("invested-value").textContent = presentMoney(data.invested_value, currency);
        byId("cash-value").textContent = presentMoney(data.cash_value, currency);
        byId("contributions-value").textContent = presentMoney(data.net_contributions, currency);
        byId("as-of").textContent = `As of ${presentTime(envelope.as_of || data.valuation_at)}`;

        const state = envelope.data_quality?.state;
        const quality = typeof state === "string" && state.length <= 30 ? state : "unknown";
        qualityBadge.textContent = `Quality: ${quality}`;
        qualityBadge.dataset.state = quality;
        qualityBadge.hidden = false;
        syntheticBadge.hidden = data.synthetic_data !== true;
        byId("quality-note").textContent = typeof data.quality_disclosure === "string" && data.quality_disclosure.length <= 4096 ? data.quality_disclosure : "Data quality disclosure is unavailable.";
        empty.hidden = true;
        content.hidden = false;
      };

      const updateFromToolResult = (result) => {
        try {
          render(result?.isError || result?.is_error ? null : result?.structuredContent ?? result?.structured_content ?? result);
        } catch (_) {
          render(null);
        }
      };

      const request = (method, params) => new Promise((resolve, reject) => {
        const id = ++rpcId;
        pending.set(id, { resolve, reject });
        window.parent.postMessage({ jsonrpc: "2.0", id, method, params }, "*");
      });

      const notify = (method, params) => {
        window.parent.postMessage({ jsonrpc: "2.0", method, params }, "*");
      };

      window.addEventListener("message", (event) => {
        if (event.source !== window.parent) return;
        const message = event.data;
        if (!message || message.jsonrpc !== "2.0") return;
        if (message.id !== undefined && !message.method && pending.has(message.id)) {
          const promise = pending.get(message.id);
          pending.delete(message.id);
          if (message.error) promise.reject(message.error);
          else promise.resolve(message.result);
          return;
        }
        if (message.id === undefined && ["ui/notifications/tool-result", "ui/notifications/tool-input", "ui/notifications/tool-input-partial", "ui/notifications/tool-cancelled"].includes(message.method)) {
          receivedToolNotification = true;
        }
        if (message.id === undefined && ["ui/notifications/tool-input", "ui/notifications/tool-input-partial", "ui/notifications/tool-cancelled"].includes(message.method)) {
          render(null);
          empty.textContent = message.method === "ui/notifications/tool-cancelled"
            ? "Tool execution was cancelled. No current result is displayed."
            : "Waiting for the authorized tool result. Input arguments are not results.";
        }
        if (message.id === undefined && message.method === "ui/notifications/tool-result") {
          updateFromToolResult(message.params);
        }
      }, { passive: true });

      // Compatibility fallback is presentation-only; the MCP Apps bridge remains primary.
      if (window.openai?.toolOutput) updateFromToolResult(window.openai.toolOutput);

      request("ui/initialize", {
        appInfo: { name: "trading212-portfolio-snapshot", version: "1.0.0" },
        appCapabilities: {},
        protocolVersion: "2026-01-26",
      }).then(() => notify("ui/notifications/initialized", {})).catch(() => {
        if (!receivedToolNotification && window.openai?.toolOutput) updateFromToolResult(window.openai.toolOutput);
      });
    })();
  </script>
</body>
</html>
""".strip()


# Hash the exact static script/style bytes, including their surrounding whitespace.
_SCRIPT = SNAPSHOT_WIDGET_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
_STYLE = SNAPSHOT_WIDGET_HTML.split("<style>", 1)[1].split("</style>", 1)[0]


def _hash(value: str) -> str:
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode("ascii")


_CSP = (
    "default-src 'none'; connect-src 'none'; img-src 'none'; font-src 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; "
    f"script-src 'sha256-{_hash(_SCRIPT)}'; style-src 'sha256-{_hash(_STYLE)}'"
)
SNAPSHOT_WIDGET_HTML = SNAPSHOT_WIDGET_HTML.replace(
    '  <meta charset="utf-8">',
    f'  <meta charset="utf-8">\n  <meta http-equiv="Content-Security-Policy" content="{_CSP}">',
    1,
)
