# syntax=docker/dockerfile:1
# Two stages: uv resolves the lock once, the runtime carries only the venv and the code.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY . .
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
# git is not optional: deterministic extraction dates undated files from `git log`.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'  # mounts are host-owned
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CORPUS_ROOT=/corpus \
    NEO4J_URI=bolt://neo4j:7687 \
    HOST=0.0.0.0 \
    PORT=8000
COPY --from=build /app /app
# The corpus is mounted read-only at /corpus; nothing is written outside the graph.
EXPOSE 8000
CMD ["python", "-m", "cli", "serve"]
