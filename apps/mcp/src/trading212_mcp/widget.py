# ruff: noqa: E501
"""Versioned, dependency-free portfolio snapshot MCP Apps resource."""

from __future__ import annotations

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
    .hero-value { margin-top: 3px; font-size: clamp(30px, 8vw, 46px); line-height: 1.05; letter-spacing: -0.045em; font-weight: 720; }
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
      const pending = new Map();

      const presentMoney = (metric, fallbackCurrency) => {
        if (!metric || metric.value === null || metric.value === undefined) return "Unavailable";
        const currency = metric.reporting_currency || fallbackCurrency;
        const text = String(metric.value);
        if (!/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(text)) return "Unavailable";
        const numeric = Number(text);
        if (!Number.isFinite(numeric) || !currency) return `${text} ${currency || ""}`.trim();
        try {
          return new Intl.NumberFormat(document.documentElement.lang || "en", {
            style: "currency",
            currency,
            maximumFractionDigits: 2,
          }).format(numeric);
        } catch (_) {
          return `${text} ${currency}`;
        }
      };

      const presentTime = (value) => {
        const timestamp = new Date(value);
        if (Number.isNaN(timestamp.getTime())) return "—";
        return new Intl.DateTimeFormat(document.documentElement.lang || "en", {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(timestamp);
      };

      const render = (envelope) => {
        if (!envelope || envelope.error || !envelope.data) {
          empty.textContent = envelope?.error?.message || "Portfolio snapshot data is unavailable.";
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

        const quality = envelope.data_quality?.state || "unknown";
        qualityBadge.textContent = `Quality: ${quality}`;
        qualityBadge.dataset.state = quality;
        qualityBadge.hidden = false;
        syntheticBadge.hidden = !data.synthetic_data;
        byId("quality-note").textContent = data.quality_disclosure || "Data quality is shown explicitly.";
        empty.hidden = true;
        content.hidden = false;
      };

      const updateFromToolResult = (result) => {
        const structured = result?.structuredContent || result?.structured_content || result;
        render(structured);
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
        if (message.id !== undefined && pending.has(message.id)) {
          const promise = pending.get(message.id);
          pending.delete(message.id);
          if (message.error) promise.reject(message.error);
          else promise.resolve(message.result);
          return;
        }
        if (message.method === "ui/notifications/tool-result") {
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
        if (window.openai?.toolOutput) updateFromToolResult(window.openai.toolOutput);
      });
    })();
  </script>
</body>
</html>
""".strip()
