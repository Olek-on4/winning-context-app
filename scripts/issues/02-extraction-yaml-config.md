# ingest: read `compose.yaml` and `pnpm-workspace.yaml` as config claims

Lane A (Extraction). Owner: unclaimed.

## Problem

`JsonConfigMap` covers JSON objects of name → scalar. The corpus's real config is YAML, so
`compose.yaml` (service → image/ports) and `pnpm-workspace.yaml` (workspace packages) produce
no claims. `docs/10-workstreams.md` §A lists both under the ConfigPipeline, and
`docs/02-architecture.md` treats compose as the source of service topology.

## Evidence

```
$ find vendor/att-hackathon-task -name '*.yaml' -o -name '*.yml'
vendor/att-hackathon-task/compose.yaml
vendor/att-hackathon-task/pnpm-workspace.yaml
vendor/att-hackathon-task/.github/workflows/ci.yml
```

`ingest/registry.py` has no `yaml` import; `pyproject.toml` does not depend on a YAML parser.

## Change

- Add `PyYAML` (or `ruamel.yaml`) to `apps/context-service/pyproject.toml`.
- One `YamlConfig` pipeline: `matches()` on suffix `.yaml`/`.yml`, `extract()` yields
  `LISTENS_ON` for compose `ports`, `RUNS_IMAGE` for `image`, `MEMBER_OF` for workspace
  globs. Skip files where the top-level key is absent — a workflow file is not a config map
  we understand yet, and silence beats a wrong claim.
- Span: `_line_containing` already gives the line; the gate drops anything whose text is
  missing at that line, so no new gate mechanism is needed.

## Acceptance

- `cli extract` on the submodule emits ≥1 `LISTENS_ON` claim citing
  `att-hackathon-task/compose.yaml` with the correct line.
- A YAML file with no recognised top-level key emits zero claims (unit test in
  `tests/test_agnostic.py` style, temp corpus, no Neo4j).
