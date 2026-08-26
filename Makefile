# SARANA - single entry point for every development task.
# Run `make` or `make help` for the list.

SHELL := /bin/bash
.DEFAULT_GOAL := help
.ONESHELL:

COMPOSE := docker compose -f infra/docker/compose.yml --env-file .env
UV := uv

# Every FastAPI service.
SERVICES := core-api incident-svc alerting-svc ledger-svc agent-svc gov-mock
# Services that own tables and therefore own an alembic tree.
DATA_SERVICES := core-api incident-svc alerting-svc ledger-svc agent-svc

DEV_KEYS := infra/docker/dev-keys

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.env:
	@cp .env.example .env
	@echo "Created .env from .env.example - review it before running make up."

$(DEV_KEYS)/jwt-private.pem:
	@mkdir -p $(DEV_KEYS)
	@openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
		-out $(DEV_KEYS)/jwt-private.pem 2>/dev/null
	@openssl rsa -in $(DEV_KEYS)/jwt-private.pem -pubout \
		-out $(DEV_KEYS)/jwt-public.pem 2>/dev/null
	@echo "Generated a development RS256 keypair in $(DEV_KEYS). Local use only."

.PHONY: keys
keys: $(DEV_KEYS)/jwt-private.pem ## Generate the local RS256 JWT keypair

.PHONY: bootstrap
bootstrap: .env keys ## Install Python + Node dependencies and git hooks
	$(UV) sync --all-packages --all-groups
	pnpm install --frozen-lockfile || pnpm install
	$(UV) run pre-commit install --install-hooks
	@echo ""
	@echo "Bootstrap complete. Next: make up"

.PHONY: up
up: .env keys ## Start the stack, wait for health, migrate and seed
	$(COMPOSE) up -d --build --wait
	@echo "All containers healthy. Creating object storage buckets..."
	$(COMPOSE) run --rm minio-init
	@echo "Applying migrations..."
	$(MAKE) migrate
	$(MAKE) seed
	@echo ""
	@$(MAKE) --no-print-directory ports

.PHONY: down
down: ## Stop and remove containers, keep volumes
	$(COMPOSE) down --remove-orphans

.PHONY: reset
reset: ## DESTRUCTIVE - delete all volumes and rebuild from empty
	@read -r -p "This deletes the local database, MinIO objects and Redis streams. Type 'reset' to confirm: " reply
	@if [[ "$$reply" != "reset" ]]; then echo "Aborted."; exit 1; fi
	$(COMPOSE) down --volumes --remove-orphans
	$(MAKE) up

.PHONY: migrate
migrate: ## Run alembic upgrade head for every data-owning service
	@set -e
	@for svc in $(DATA_SERVICES); do \
		echo "--> migrating $$svc"; \
		(cd services/$$svc && $(UV) run alembic upgrade head); \
	done

.PHONY: revision
revision: ## Autogenerate a migration. Usage: make revision SVC=ledger-svc M="add grievance"
	@if [[ -z "$(SVC)" || -z "$(M)" ]]; then \
		echo "Usage: make revision SVC=<service> M=\"<message>\""; exit 1; fi
	cd services/$(SVC) && $(UV) run alembic revision --autogenerate -m "$(M)"

.PHONY: seed
seed: ## Load data/seed reference and scenario data
	$(UV) run python -m sarana_shared.seed.load --path data/seed

.PHONY: dev
dev: ## Run web and mobile in watch mode alongside the compose stack
	pnpm turbo run dev

.PHONY: test
test: ## Run pytest across services and vitest across TS packages
	$(UV) run pytest
	pnpm turbo run test

.PHONY: lint
lint: ## ruff check + ruff format --check + mypy + eslint + tsc --noEmit
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy packages/py-shared/src $(wildcard services/*/src)
	pnpm turbo run lint typecheck

.PHONY: fmt
fmt: ## Auto-fix formatting and import order
	$(UV) run ruff check --fix .
	$(UV) run ruff format .
	pnpm run format

.PHONY: openapi
openapi: ## Regenerate the merged OpenAPI spec and the TypeScript client
	$(UV) run python -m sarana_shared.openapi.merge --out packages/ts-shared/openapi.json
	pnpm --filter @sarana/ts-shared run generate:api

.PHONY: verify-i18n
verify-i18n: ## Fail if any locale key is missing in si, ta or en
	pnpm --filter @sarana/ts-shared run verify-i18n
	$(UV) run python -m sarana_shared.domain.i18n_check

.PHONY: logs
logs: ## Tail logs for the whole stack, or one service: make logs SVC=core-api
	$(COMPOSE) logs -f --tail=100 $(SVC)

.PHONY: ports
ports: ## Print the local port map
	@echo "  core-api      http://localhost:8001   incident-svc  http://localhost:8002"
	@echo "  alerting-svc  http://localhost:8003   ledger-svc    http://localhost:8004"
	@echo "  agent-svc     http://localhost:8005   gov-mock      http://localhost:8006"
	@echo "  web-ops       http://localhost:3000   web-public    http://localhost:3001"
	@echo "  postgres      localhost:5432          redis         localhost:6379"
	@echo "  minio api     http://localhost:9000   minio console http://localhost:9001"
	@echo "  jaeger        http://localhost:16686  mailpit       http://localhost:8025"

.PHONY: health
health: ## Curl /healthz on all six services
	@set -e
	@for port in 8001 8002 8003 8004 8005 8006; do \
		printf "  :%s " $$port; curl -fsS localhost:$$port/healthz && echo; \
	done
