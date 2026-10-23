# QA Admin Portal — convenience targets around docker-compose.
# Stack: postgres + seaweedfs + api (FastAPI :8000) + web (nginx :8080).

COMPOSE := docker compose
WEB_URL := http://localhost:8080
API_URL := http://localhost:8000

.DEFAULT_GOAL := help

.PHONY: help up down start stop restart build rebuild logs ps health open dev-web dev-api clean \
        test lint ci-test check bootstrap deliver reset

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

docker-up: # Ensure the Docker daemon is running (starts Docker Desktop on macOS and waits).
	@if ! docker info >/dev/null 2>&1; then \
		echo "Docker daemon not running — starting Docker Desktop..."; \
		open -a Docker || { echo "Could not launch Docker Desktop; start it manually."; exit 1; }; \
		printf "Waiting for Docker"; \
		until docker info >/dev/null 2>&1; do printf "."; sleep 1; done; \
		echo " ready."; \
	fi

up: docker-up ## Build (if needed) and start the whole stack in the background
	$(COMPOSE) up -d --build
	@echo "Portal: $(WEB_URL)   API: $(API_URL)/health"

start: docker-up ## Start the stack without rebuilding
	$(COMPOSE) up -d
	@echo "Portal: $(WEB_URL)   API: $(API_URL)/health"

down: ## Stop and remove containers + network (named volumes/data kept)
	$(COMPOSE) down

stop: ## Stop containers but keep them (faster next start)
	$(COMPOSE) stop

restart: ## Restart all running services
	$(COMPOSE) restart

build: docker-up ## Build images without starting
	$(COMPOSE) build

rebuild: docker-up ## Rebuild images from scratch (no cache) and restart
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

logs: ## Follow logs from all services (Ctrl-C to stop)
	$(COMPOSE) logs -f

ps: ## Show container status
	$(COMPOSE) ps

health: ## Curl the API health endpoint and web root
	@echo "API:" && curl -sf -m 5 $(API_URL)/health && echo "" || echo "  API not responding"
	@echo "Web:" && curl -s -m 5 -o /dev/null -w "  HTTP %{http_code}\n" $(WEB_URL) || echo "  Web not responding"

open: ## Open the portal in the default browser
	@open $(WEB_URL) || echo "Open $(WEB_URL) manually"

dev-web: ## Run the Vite dev server for the web app (hot reload, :5173)
	cd web && npm run dev

dev-api: docker-up ## Run uvicorn with --reload for the API (needs Postgres up: make start)
	cd server && uv run uvicorn app.main:app --reload

clean: ## Stop everything and DELETE data volumes (destructive)
	$(COMPOSE) down -v

test: lint ## Run CI's three checks: ruff + backend pytest + frontend vitest
	cd server && uv run pytest
	cd web && npm test

lint: ## Lint the backend (ruff). Run by `make test` and by CI
	cd server && uv run ruff check .

ci-test: ## `make test` as CI runs it: fails instead of skipping if Postgres is absent
	QA_REQUIRE_DB=1 $(MAKE) test

# --- target-repo delivery (app/delivery; was scripts/*.sh) ---------------
# APP and STORY are required where shown. GITHUB_PAT comes from the environment
# or .env (the `gh auth token` fallback is gone with `gh`).
#
# Each of these is also an API route (POST /targets/<id>/deliver, /reset,
# GET /targets/<id>/bootstrapped), but only the bootstrap form is wired into the
# portal UI so far -- delivery and reset are CLI- or API-only today.

check: ## Is APP's target repo bootstrapped? (read-only) — make check APP=saucedemo
	@test -n "$(APP)" || { echo "usage: make check APP=<app>"; exit 2; }
	cd server && uv run python -m app.delivery check $(APP)

bootstrap: ## Sync infra files to APP's target repo — make bootstrap APP=saucedemo [DRY=1]
	@test -n "$(APP)" || { echo "usage: make bootstrap APP=<app> [DRY=1]"; exit 2; }
	cd server && uv run python -m app.delivery bootstrap $(APP) $(if $(DRY),--dry-run,)

deliver: ## Deliver one story as a PR — make deliver APP=saucedemo STORY=SCRUM-101 [DRY=1]
	@test -n "$(APP)" -a -n "$(STORY)" || { echo "usage: make deliver APP=<app> STORY=<ID> [DRY=1]"; exit 2; }
	cd server && uv run python -m app.delivery push $(APP) $(STORY) $(if $(DRY),--dry-run,)

reset: ## DESTRUCTIVE: wipe APP's target repo — make reset APP=x CONFIRM=owner/repo [DRY=1]
	@test -n "$(APP)" || { echo "usage: make reset APP=<app> CONFIRM=<owner/repo> [DRY=1]"; exit 2; }
	cd server && uv run python -m app.delivery reset $(APP) \
		$(if $(DRY),--dry-run,--confirm-repo $(CONFIRM))
