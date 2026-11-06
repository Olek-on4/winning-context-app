# etynt_gui — web UI for the Northstar Context Service

A standalone React + Vite app. It talks to the service only over `/v1/*` with relative
paths, so the server that serves this page also serves the API: no proxy, no CORS.

```sh
npm ci && npm run build          # → dist/   (npm run build -- --watch while developing)
cd ../apps/context-service && uv run python -m cli serve   # UI + API on :8000
```

`create_app` mounts `etynt_gui/dist` at `/` when it exists (override with `WEB_DIST`);
without a build the server is API-only.

What the UI does with an answer:

- **Current** — `VALID` and confidence ≥ 0.40: the only claims the answer rests on.
- **Not valid** — everything else, each with the reason (superseded by, planned, disputed,
  too weak). Uses the envelope's `not_valid` when the service sends it.
- Citations open the exact lines via `/v1/span`; the text is shown verbatim, never interpreted.
- `?q=…&as_of=YYYY-MM-DD` in the URL: answers are shareable links and Back works.
