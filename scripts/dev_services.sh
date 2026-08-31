#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:=postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio}"
: "${CELERY_BROKER_URL:=redis://127.0.0.1:6379/0}"
: "${T212PI_ENVIRONMENT:=local}"
: "${T212PI_LOCAL_SYNTHETIC_AUTH_ENABLED:=true}"
: "${T212PI_COOKIE_SECURE:=false}"
: "${T212PI_API_BASE_URL:=http://127.0.0.1:8000}"
: "${T212PI_LOCAL_API_AUTH_ENABLED:=1}"
: "${T212PI_WEB_ENVIRONMENT:=local}"
if [[ -z "${T212PI_ALLOWED_ORIGINS:-}" ]]; then
  T212PI_ALLOWED_ORIGINS='["http://127.0.0.1:3000","http://localhost:3000"]'
fi
if [[ -z "${T212PI_ALLOWED_HOSTS:-}" ]]; then
  T212PI_ALLOWED_HOSTS='["127.0.0.1","localhost"]'
fi
export DATABASE_URL CELERY_BROKER_URL
export T212PI_ENVIRONMENT T212PI_LOCAL_SYNTHETIC_AUTH_ENABLED T212PI_COOKIE_SECURE
export T212PI_ALLOWED_ORIGINS T212PI_ALLOWED_HOSTS
export T212PI_API_BASE_URL T212PI_LOCAL_API_AUTH_ENABLED T212PI_WEB_ENVIRONMENT

uv run uvicorn trading212_api.main:app --host 127.0.0.1 --port 8000 --reload &
api_pid=$!
corepack pnpm --filter @trading212/web dev &
web_pid=$!

cleanup() {
  kill "$api_pid" "$web_pid" 2>/dev/null || true
  wait "$api_pid" "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait -n "$api_pid" "$web_pid"
