# syntax=docker/dockerfile:1
# Three stages: a static artefact stage for the built UI, a uv stage that resolves the
# lock once, and a runtime that carries only the venv, the code and the built UI.
#
# The build context is the REPO ROOT, not this directory: the UI stage needs etynt_gui,
# the API stage needs apps/context-service, and .dockerignore trims everything else.
#
# Embeddings come from a sibling `ollama` service (see infra/neo4j/compose.yaml), not
# from this image. CPU inference is the default in-container path: no GPU is required
# and `ollama` silently falls back to CPU when no device is visible. GPU inference
# needs nvidia-container-toolkit on the host plus the `deploy.resources.reservations
# .devices` block in the compose file (left commented out there).
FROM busybox:1.36 AS ui
# The UI is built on the host (`make ui-build`), not in the image: a Node stage would
# need npm-registry access at build time, which an air-gapped or proxied build host does
# not have, and the artefact is a few hundred kilobytes of static files either way.
# `etynt_gui/dist` is therefore part of the build context (see .dockerignore) and this
# stage fails loudly if it is missing rather than shipping an API-only image by accident.
COPY etynt_gui/dist /ui/dist
RUN test -f /ui/dist/index.html || { echo "etynt_gui/dist is empty: run 'make ui-build' first" >&2; exit 1; }

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY apps/context-service/pyproject.toml apps/context-service/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY apps/context-service/ ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
# git is not optional: deterministic extraction dates undated files from `git log`.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'  # mounts are host-owned
WORKDIR /app
# No root at runtime (issue #88). uid/gid 1000 is the usual host user, so the bind-mounted
# corpus is readable and /data writable without `--user` overrides. WORKDIR is owned by
# the app user because Python writes __pycache__ next to the modules.
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/corpus /data/local \
    && chown -R app:app /app /data
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    NEO4J_URI=bolt://neo4j:7687 \
    HOST=0.0.0.0 \
    PORT=8000 \
    WEB_DIST=/app/web \
    CORPUS_ROOT=/app/corpus
# --chown keeps the ownership without an extra layer that copies the whole tree.
COPY --chown=app:app --from=build /app /app
COPY --chown=app:app --from=ui /ui/dist /app/web
# The image carries no corpus: /app/corpus is an empty root so `cli serve` boots and
# answers /healthz with no mount at all. Extraction and span resolution need the real
# corpus, which compose supplies at /repo (read-only); point CORPUS_ROOT there.
USER app
EXPOSE 8000
CMD ["python", "-m", "cli", "serve"]
