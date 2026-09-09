SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

UV ?= uv
PNPM ?= corepack pnpm
COMPOSE ?= $(shell if docker compose version >/dev/null 2>&1; then printf '%s' 'docker compose'; elif command -v docker-compose >/dev/null 2>&1; then printf '%s' docker-compose; else printf '%s' 'docker compose'; fi)
TMPDIR ?= /tmp
export TMPDIR
LOCAL_DATABASE_URL ?= postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio
LOCAL_REDIS_URL ?= redis://127.0.0.1:6379/0
SEMGREP_IMAGE ?= semgrep/semgrep:1.175.0@sha256:b94b53d02fd4a022f9eac4e2af1380f5c3c4c21400e79d3336bdff1d1db5e796
GITLEAKS_IMAGE := ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
PYTHON_TARGETS := apps packages scripts tests

.PHONY: help bootstrap check-workspace format format-check lint lint-python lint-web \
	typecheck typecheck-python typecheck-web test-unit test-property test-contract \
	test-integration test-migrations test-security test-e2e docs-check security-check \
	sast-check architecture-check build build-python build-web test validate security dev \
	run-dependencies run-local stop-local migrate seed-demo generated-check container-build \
	smoke-trading212-demo test-coverage

help: ## Show the available developer commands.
	@awk 'BEGIN {FS = ":.*## "} /^[A-Za-z0-9_.-]+:.*## / {printf "%-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install exact Python and Node workspace locks, then validate them.
	@command -v $(UV) >/dev/null
	@command -v corepack >/dev/null
	@test "$$($(UV) run python -c 'import platform; print(platform.python_version())')" = "3.13.15"
	@corepack prepare pnpm@10.34.5 --activate >/dev/null
	$(UV) sync --frozen --all-packages --all-groups
	$(PNPM) install --frozen-lockfile
	$(PNPM) --filter @trading212/web exec playwright install chromium
	$(MAKE) check-workspace

check-workspace: ## Validate exact runtimes, dependency pins, lockfiles, and workspace boundaries.
	$(UV) run python scripts/check_workspace.py

format: ## Format Python and TypeScript sources deterministically.
	$(UV) run ruff format $(PYTHON_TARGETS)
	$(UV) run ruff check --fix $(PYTHON_TARGETS)
	$(PNPM) format

format-check: ## Check formatting without modifying files.
	$(UV) run ruff format --check $(PYTHON_TARGETS)
	$(PNPM) format:check

lint-python: ## Run Python static lint checks.
	$(UV) run ruff check $(PYTHON_TARGETS)

lint-web: ## Run all workspace ESLint checks.
	$(PNPM) lint

architecture-check: ## Enforce package direction and the sealed Trading 212 GET-only boundary.
	$(UV) run python scripts/check_architecture.py
	$(UV) run python scripts/check_trading212_boundary.py

lint: lint-python lint-web architecture-check ## Run all language and architecture linters.

typecheck-python: ## Run strict mypy across application, package, script, and test code.
	$(UV) run mypy $(PYTHON_TARGETS)

typecheck-web: ## Run strict TypeScript checks in every pnpm package.
	$(PNPM) typecheck

typecheck: typecheck-python typecheck-web ## Run strict Python and TypeScript type checks.

test-unit: ## Run deterministic Python and TypeScript unit tests.
	$(UV) run pytest tests/unit
	$(PNPM) test:unit

test-property: ## Run Hypothesis invariant tests.
	$(UV) run pytest tests/property

test-contract: check-workspace ## Run package/provider/API contract tests available at this increment.
	$(UV) run python scripts/generate_api_contract.py --check
	$(UV) run pytest tests/contract

test-integration: ## Start PostgreSQL 18/Redis and run real service integration tests.
	$(COMPOSE) up -d postgres redis
	TEST_DATABASE_URL="$${TEST_DATABASE_URL:-postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio}" REDIS_URL="$${REDIS_URL:-redis://127.0.0.1:6379/0}" $(UV) run python scripts/wait_for_services.py --redis
	TEST_DATABASE_URL="$${TEST_DATABASE_URL:-postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio}" REDIS_URL="$${REDIS_URL:-redis://127.0.0.1:6379/0}" $(UV) run pytest -m "integration and not migrations"

test-migrations: ## Apply migrations twice to a disposable clean PostgreSQL 18 database.
	$(COMPOSE) up -d postgres
	TEST_DATABASE_URL="$${TEST_DATABASE_URL:-postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio}" $(UV) run python scripts/wait_for_services.py
	TEST_DATABASE_URL="$${TEST_DATABASE_URL:-postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio}" $(UV) run pytest tests/integration/test_migrations.py

test-security: architecture-check ## Run negative security and secret-canary tests.
	$(UV) run python scripts/check_secrets.py
	$(UV) run pytest tests/security

test-coverage: ## Enforce branch-aware coverage across isolated and service-backed code.
	$(COMPOSE) up -d postgres redis
	TEST_DATABASE_URL="$${TEST_DATABASE_URL:-postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio}" REDIS_URL="$${REDIS_URL:-redis://127.0.0.1:6379/0}" $(UV) run python scripts/wait_for_services.py --redis
	$(UV) run coverage erase
	TEST_DATABASE_URL="$${TEST_DATABASE_URL:-postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio}" REDIS_URL="$${REDIS_URL:-redis://127.0.0.1:6379/0}" $(UV) run coverage run -m pytest tests/unit tests/property tests/contract tests/security
	TEST_DATABASE_URL="$${TEST_DATABASE_URL:-postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio}" REDIS_URL="$${REDIS_URL:-redis://127.0.0.1:6379/0}" $(UV) run coverage run -m pytest -m "migrations or integration"
	$(UV) run coverage combine
	$(UV) run coverage report

test-e2e: ## Run the Playwright browser smoke suite.
	$(COMPOSE) up -d postgres
	TEST_DATABASE_URL="$${TEST_DATABASE_URL:-postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio}" $(UV) run python scripts/wait_for_services.py
	$(PNPM) test:e2e

docs-check: ## Validate documentation, links, JSON, YAML contracts, and workspace metadata.
	python3 scripts/validate_repository.py
	$(UV) run python scripts/check_workspace.py

security-check: sast-check ## Audit dependencies and run source/secret security gates.
	$(UV) run python scripts/check_secrets.py
	@docker image inspect "$(GITLEAKS_IMAGE)" >/dev/null 2>&1 || docker pull "$(GITLEAKS_IMAGE)"
	$(UV) run python scripts/check_gitleaks_policy.py
	@set -euo pipefail; audit_file=$$(mktemp); \
		trap 'rm -f "$$audit_file"' EXIT; \
		$(UV) export --frozen --all-packages --no-dev --no-emit-workspace --quiet -o "$$audit_file"; \
		$(UV) tool run pip-audit==2.10.1 --requirement "$$audit_file" --disable-pip
	$(PNPM) security:dependencies

sast-check: ## Run deterministic private-repository SAST without external uploads.
	docker run --rm --network=none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=256m \
		--tmpfs /root:rw,noexec,nosuid,size=128m \
		-v "$(CURDIR):/src:ro" -w /src \
		$(SEMGREP_IMAGE) \
		semgrep scan --config .semgrep.yml --error --strict --metrics=off --no-git-ignore \
		apps packages scripts

build-python: ## Build every Python workspace distribution.
	$(UV) build --all-packages --out-dir dist/python

build-web: ## Build all TypeScript workspaces in dependency order.
	$(PNPM) build

build: build-python build-web ## Build all publishable/runtime artifacts.

generated-check: ## Verify committed generated API contracts are current.
	$(UV) run python scripts/generate_api_contract.py --check

container-build: ## Build all pinned non-root Phase 1 runtime images.
	$(COMPOSE) build postgres redis api worker mcp web
	python3 -m scripts.check_runtime_package_managers

test: test-unit test-property test-contract test-integration test-migrations test-security test-coverage test-e2e ## Run every locally executable test layer.

validate: format-check lint typecheck test docs-check security-check build container-build ## Run the complete local P1 validation gate.

security: security-check test-security ## Run dependency, secret, architecture, and negative security gates.

run-dependencies: ## Start only pinned local PostgreSQL and non-authoritative Redis.
	$(COMPOSE) up -d postgres redis
	DATABASE_URL="$${DATABASE_URL:-$(LOCAL_DATABASE_URL)}" REDIS_URL="$${REDIS_URL:-$(LOCAL_REDIS_URL)}" $(UV) run python scripts/wait_for_services.py --redis

run-local: ## Build and start the complete migrated, seeded Phase 1 stack.
	$(COMPOSE) up -d --build

stop-local: ## Stop the local Compose stack without deleting named data.
	$(COMPOSE) --profile coordination stop

migrate: ## Upgrade the local PostgreSQL schema to the Alembic head.
	DATABASE_URL="$${DATABASE_URL:-$(LOCAL_DATABASE_URL)}" $(UV) run alembic -c alembic.ini upgrade head

seed-demo: ## Load the deterministic synthetic demo portfolio.
	T212PI_ENVIRONMENT="$${T212PI_ENVIRONMENT:-local}" DATABASE_URL="$${DATABASE_URL:-$(LOCAL_DATABASE_URL)}" $(UV) run python -m trading212_worker.seed

smoke-trading212-demo: ## Run the explicitly opted-in, Demo-only external GET smoke.
	$(UV) run python scripts/smoke_trading212_demo.py

dev: run-dependencies migrate seed-demo ## Start API and web development processes after local dependencies are ready.
	./scripts/dev_services.sh
