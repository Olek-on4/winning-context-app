APP := apps/context-service
# Two stacks may run on one host (issue #70): the project name and the host ports are
# both overridable, so a second stack needs no edit here.
#   make up ETYT_PROJECT=etyt-b ETYT_NEO4J_HTTP_PORT=17474 ETYT_NEO4J_BOLT_PORT=17687 \
#           ETYT_OLLAMA_PORT=21435 ETYT_APP_PORT=18000
COMPOSE := docker compose -p $(or $(ETYT_PROJECT),etyt) -f infra/neo4j/compose.yaml
APP_PORT := $(or $(ETYT_APP_PORT),8000)
# wildcard, because the extracted file is gitignored: a fresh clone has fixtures only (#85).
CLAIMS := $(wildcard ../../data/fixtures/claims-sample.jsonl ../../data/local/claims-extracted.jsonl)

.PHONY: up down extract index load serve ui ui-build mcp demo test lint fmt rehearse check install-hooks gpu e2e docker-up docker-down docker-index docker-demo models

up: ## start neo4j (waits for its healthcheck: a cold machine must not race it)
	$(COMPOSE) up -d --wait

down: ## stop neo4j
	$(COMPOSE) down

docker-up: ## neo4j + ollama + app in containers, returning only once healthy
	$(COMPOSE) up -d --build --wait

docker-down: ## stop the container stack
	$(COMPOSE) down

models: ## pull both models; fails loudly, because a missing planner is a silent downgrade
	$(COMPOSE) exec -T ollama ollama pull nomic-embed-text
	$(COMPOSE) exec -T ollama ollama pull llama3.2
	@echo "models: embedder (vectors) and planner (query translation) are present"

docker-index: ## chunk the corpus inside the app container (embeds via the ollama service)
	$(COMPOSE) exec -T app python -m cli index

docker-demo: docker-up models ## whole stack in docker, then print the query to run
	$(COMPOSE) exec -T app python -m cli extract
	$(COMPOSE) exec -T app python -m cli load /repo/data/fixtures/claims-sample.jsonl /data/local/claims-extracted.jsonl
	$(COMPOSE) exec -T app python -m cli index
	@echo "curl -s localhost:$(APP_PORT)/v1/query -H 'content-type: application/json' -d '{\"question\":\"Does inventory-service still use a Redis cache?\"}'"

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
	@echo "curl -s localhost:$(APP_PORT)/v1/query -H 'content-type: application/json' -d '{\"question\":\"Does inventory-service still use a Redis cache?\"}'"

test:
	cd $(APP) && uv run pytest -q

lint:
	cd $(APP) && uv run ruff check .

fmt:
	cd $(APP) && uv run ruff format .

e2e: ## prove the containerised stack answers REST and MCP
	cd $(APP) && ETYT_PROJECT=$(or $(ETYT_PROJECT),etyt) ETYT_APP_PORT=$(APP_PORT) \
	  uv run python ../../scripts/e2e_docker.py

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
