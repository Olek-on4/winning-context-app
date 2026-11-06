APP := apps/context-service
COMPOSE := docker compose -f infra/neo4j/compose.yaml
CLAIMS := ../../data/fixtures/claims-sample.jsonl ../../data/local/claims-extracted.jsonl

.PHONY: up down extract index load serve ui ui-build mcp demo test lint fmt rehearse check install-hooks gpu e2e docker-up docker-down docker-index docker-demo

up: ## start neo4j
	$(COMPOSE) up -d

down: ## stop neo4j
	$(COMPOSE) down

docker-up: ## neo4j + ollama + app in containers
	$(COMPOSE) up -d --build

docker-down: ## stop the container stack
	$(COMPOSE) down

docker-index: ## chunk the corpus inside the app container (embeds via etyt-ollama)
	$(COMPOSE) exec -T app python -m cli index

docker-demo: docker-up ## whole stack in docker, then print the query to run
	$(COMPOSE) exec -T ollama ollama pull nomic-embed-text
	$(COMPOSE) exec -T app python -m cli extract
	$(COMPOSE) exec -T app python -m cli load /repo/data/fixtures/claims-sample.jsonl /data/local/claims-extracted.jsonl
	$(COMPOSE) exec -T app python -m cli index
	@echo "curl -s localhost:8000/v1/query -H 'content-type: application/json' -d '{\"question\":\"Does inventory-service still use a Redis cache?\"}'"

extract: ## deterministic claims -> data/local/claims-extracted.jsonl
	cd $(APP) && uv run python -m cli extract

index: ## chunk the corpus for hybrid search
	cd $(APP) && uv run python -m cli index

load: ## fixtures + extracted claims into the graph
	cd $(APP) && uv run python -m cli load $(CLAIMS)

serve: ## REST on :8000 (API only; use `make ui` for the web page)
	cd $(APP) && uv run python -m cli serve

ui-build: ## npm ci + vite build into etynt_gui/dist
	cd etynt_gui && { test -d node_modules || npm ci; } && npm run build

ui: ## build the web UI when stale, then serve page + API on :8000
	@test -f etynt_gui/dist/index.html \
	  && [ -z "$$(find etynt_gui/src etynt_gui/index.html -newer etynt_gui/dist/index.html)" ] \
	  || $(MAKE) --no-print-directory ui-build
	cd $(APP) && WEB_DIST=$$PWD/../../etynt_gui/dist uv run python -m cli serve

mcp: ## MCP over stdio
	cd $(APP) && uv run python -m cli mcp

demo: up extract load index ## bring-up, then print the query to run
	@echo "curl -s localhost:8000/v1/query -H 'content-type: application/json' -d '{\"question\":\"Does inventory-service still use a Redis cache?\"}'"

test:
	cd $(APP) && uv run pytest -q

lint:
	cd $(APP) && uv run ruff check .

fmt:
	cd $(APP) && uv run ruff format .

e2e: ## prove the containerised stack answers REST and MCP
	cd $(APP) && uv run python ../../scripts/e2e_docker.py

rehearse:
	cd $(APP) && uv run python ../../scripts/rehearse.py

check: lint test ## the commit gate

gpu: ## is the model actually on the card?
	@nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "no driver loaded"
	@ollama ps 2>/dev/null || echo "ollama not installed"

install-hooks: ## point git at .githooks
	bash scripts/install-hooks.sh

issues: ## file the work queue as issues, skipping titles that already exist
	bash scripts/file-issues.sh
