# QA Admin Portal — convenience targets around docker-compose.
# Stack: postgres + seaweedfs + api (FastAPI :8000) + web (nginx :8080).

COMPOSE := docker compose
WEB_URL := http://localhost:8080
API_URL := http://localhost:8000

.DEFAULT_GOAL := help

.PHONY: help up down start stop restart build rebuild logs ps health open dev-web dev-api clean

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

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
