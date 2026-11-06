APP := apps/context-service
COMPOSE := docker compose -f infra/neo4j/compose.yaml
CLAIMS := ../../data/fixtures/claims-sample.jsonl ../../data/local/claims-extracted.jsonl

.PHONY: up down extract index load serve mcp demo test lint fmt rehearse check install-hooks gpu docker-up docker-down docker-index docker-demo

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

serve: ## REST on :8000
	cd $(APP) && uv run python -m cli serve

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
