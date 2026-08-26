.PHONY: bootstrap up down reset migrate seed dev test lint openapi verify-i18n

COMPOSE := docker compose -f infra/docker/compose.yml

# ---------------------------------------------------------------------------
bootstrap: ## install uv + pnpm deps, install pre-commit hooks
	uv sync --all-packages --all-extras --group dev
	pnpm install
	uv run --group dev pre-commit install

# ---------------------------------------------------------------------------
up: ## docker compose up -d, wait for health, run migrations, seed
	$(COMPOSE) up -d --build
	@echo "Waiting for all six services to report healthy..."
	@for port in 8001 8002 8003 8004 8005 8006; do \
		echo -n "  :$$port "; \
		for i in $$(seq 1 30); do \
			if curl -fsS "http://localhost:$$port/healthz" > /dev/null 2>&1; then echo "ok"; break; fi; \
			if [ $$i -eq 30 ]; then echo "TIMED OUT"; exit 1; fi; \
			sleep 2; \
		done; \
	done
	$(MAKE) migrate
	$(MAKE) seed

down: ## stop and remove
	$(COMPOSE) down

reset: ## down + delete volumes + up (destructive, prompts for confirmation)
	@echo "This deletes all local SARANA data (Postgres, MinIO). Continue? [y/N]" && read ans && [ "$$ans" = "y" ]
	$(COMPOSE) down -v
	$(MAKE) up

# ---------------------------------------------------------------------------
migrate: ## alembic upgrade head across all data-owning services
	@for svc in core-api incident-svc alerting-svc ledger-svc agent-svc; do \
		if [ -d "services/$$svc/alembic" ] && [ -n "$$(ls -A services/$$svc/alembic/versions 2>/dev/null)" ]; then \
			echo "Migrating $$svc..."; \
			(cd services/$$svc && uv run --project . alembic upgrade head); \
		else \
			echo "Skipping $$svc — no migrations yet (docs/build-prompts/04-data-model.md not built)"; \
		fi; \
	done

seed: ## load data/seed into the database
	@if [ -f tools/seed/load.py ]; then \
		uv run python tools/seed/load.py; \
	else \
		echo "Skipping seed — tools/seed/ not built yet (docs/build-prompts/28-simulation-and-seed-data.md)"; \
	fi

# ---------------------------------------------------------------------------
dev: ## turbo dev (web + mobile) alongside the compose stack
	$(COMPOSE) up -d postgres redis minio jaeger mailpit
	pnpm run dev

# ---------------------------------------------------------------------------
test: ## pytest across services + vitest across packages
	uv run --group dev pytest packages services
	pnpm run test

lint: ## ruff + eslint + tsc --noEmit
	uv run --group dev ruff check .
	uv run --group dev ruff format --check .
	pnpm run lint
	pnpm run typecheck

test-invariants: ## the dedicated non-negotiable-proving suite (docs/build-prompts/29-testing-and-cicd.md)
	@if [ -d tests/invariants ]; then \
		uv run --group dev pytest tests/invariants -v; \
	else \
		echo "Skipping — tests/invariants/ not built yet (docs/build-prompts/29-testing-and-cicd.md)"; \
	fi

# ---------------------------------------------------------------------------
openapi: ## regenerate the merged OpenAPI spec and the TS client
	@echo "Not built yet — needs real endpoints beyond /healthz first (docs/build-prompts/07 onward)."

verify-i18n: ## fail if any locale key is missing in si, ta, or en
	node tools/i18n/verify.mjs
