// The demo surface: the same four tools the stdio MCP server registers, called over
// HTTP, with the request and the raw response shown next to each other.
import { useEffect, useState } from 'react'
import * as api from './api'

type Citation = { path: string; lines: [number, number] }

const pretty = (value: unknown) => JSON.stringify(value, null, 2)

function Citations({ result, onSpan }: { result: Record<string, unknown>; onSpan: (c: Citation) => void }) {
  const claims = (result.claims as { statement: string; status: string; citations?: Citation[] }[]) ?? []
  const cited = claims.flatMap((c) => (c.citations ?? []).map((cit) => ({ ...cit, statement: c.statement })))
  if (cited.length === 0) return null
  return (
    <div className="bin stack">
      <div className="section-head cluster">
        <h3>Citations</h3>
        <span className="count">click to read the source bytes</span>
      </div>
      <div className="stack">
        {cited.slice(0, 8).map((c) => (
          <button key={`${c.path}:${c.lines[0]}:${c.statement}`} type="button" className="source" onClick={() => onSpan(c)}>
            <span><code>{c.path}:{c.lines[0]}-{c.lines[1]}</code><small>{c.statement}</small></span>
            <b>-&gt;</b>
          </button>
        ))}
      </div>
    </div>
  )
}

export default function DeveloperView() {
  const [tools, setTools] = useState<api.ToolSpec[]>([])
  const [name, setName] = useState('context_search')
  // One value per parameter of the selected tool, seeded from the spec the service sends.
  const [values, setValues] = useState<Record<string, string>>({})
  const [span, setSpan] = useState<{ path: string; text: string } | null>(null)
  const [call, setCall] = useState<api.ToolCall | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [, force] = useState(0)

  useEffect(() => {
    api
      .mcpTools()
      .then((list) => {
        setTools(list)
        // Seed the first tool's fields: an empty form posts no `question` and the
        // server rightly rejects it.
        const first = list.find((t) => t.name === name) ?? list[0]
        if (first) setValues(seed(first))
      })
      .catch((e: Error) => setError(e.message))
    const off = api.subscribe(() => force((n) => n + 1))
    return () => {
      off()
    }
  }, [])

  const spec = tools.find((t) => t.name === name)

  const seed = (spec: api.ToolSpec): Record<string, string> => {
    const out: Record<string, string> = {}
    for (const [key, p] of Object.entries(spec.params)) {
      out[key] =
        key === 'question'
          ? 'Does inventory-service still use a Redis cache?'
          : key === 'path'
            ? 'docs/adr/003-stock-cache.md'
            : key === 'start'
              ? '6'
              : key === 'end'
                ? '12'
                : p.default !== undefined
                  ? String(p.default)
                  : ''
    }
    return out
  }

  // Built from the spec, not hardcoded: a new parameter on the server appears here.
  const paramsFor = (spec: api.ToolSpec | undefined): Record<string, unknown> => {
    const out: Record<string, unknown> = {}
    for (const [key, p] of Object.entries(spec?.params ?? {})) {
      const raw = values[key] ?? ''
      if (raw === '') continue
      out[key] = p.type === 'integer' ? Number(raw) : raw
    }
    return out
  }

  const run = async () => {
    setBusy(true)
    setError('')
    setSpan(null)
    try {
      setCall(await api.mcpCall(name, paramsFor(spec)))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const readSpan = async (c: Citation) => {
    const params = new URLSearchParams({ path: c.path, start: String(c.lines[0]), end: String(c.lines[1]) })
    try {
      setSpan({ path: c.path, text: await api.span(c) })
    } catch (e) {
      setSpan({ path: c.path, text: `error: ${(e as Error).message} (${params})` })
    }
  }

  return (
    <section className="api stack">
      <div className="section-head cluster">
        <h3>API</h3>
        <span className="count">{tools.length} tools</span>
      </div>
      <p>One service, two transports: REST and MCP. The same call, shown as the request and the response.</p>

      <div className="grid grid-2">
        <div className="bin stack">
          <div className="section-head cluster">
            <h3>Tools</h3>
            <span className="count">{tools.length}</span>
          </div>
          <div className="tools stack">
            {tools.map((t) => (
              <button
                key={t.name}
                type="button"
                className={`tool ${t.name === name ? 'active' : ''}`}
                onClick={() => {
                  setName(t.name)
                  setValues(seed(t))
                  setCall(null)
                  setSpan(null)
                }}
              >
                <code>POST /v1/mcp/{t.name}</code>
                <strong>{t.intent}</strong>
                <span>{t.summary}</span>
              </button>
            ))}
          </div>

          <div className="fields stack">
            {Object.entries(spec?.params ?? {})
              .filter(([, p]) => p.required || p.type !== 'array')
              .map(([key, p]) => (
                <label key={key} className="field">
                  <span>{key}{p.required ? ' *' : ''}</span>
                  <input
                    type={p.format === 'date' ? 'date' : 'text'}
                    value={values[key] ?? ''}
                    onChange={(e) => setValues({ ...values, [key]: e.target.value })}
                    aria-label={key}
                  />
                </label>
              ))}
          </div>
          <div><button type="button" className="button" onClick={run} disabled={busy}>
            {busy ? 'Running…' : 'Run tool'}
          </button></div>

          <p className="result-where">POST /v1/mcp/{name}</p>
          <pre className="pane">{pretty({ params: paramsFor(spec) })}</pre>
        </div>

        <div className="bin stack">
          <div className="section-head cluster">
            <h3>Response</h3>
            <span className="count">{call ? (call.result.claims ? `${(call.result.claims as unknown[]).length} claims` : 'span') : 'no call yet'}</span>
          </div>
          {error ? <div className="state error"><p>{error}</p></div> : <pre className="pane">{call ? pretty(call.result) : 'Run a tool to see its answer.'}</pre>}
        </div>
      </div>

      {call && call.tool !== 'resolve_span' && <Citations result={call.result} onSpan={readSpan} />}

      {span && (
        <div className="bin stack">
          <div className="section-head cluster">
            <h3>Source bytes</h3>
            <span className="count">{span.path}</span>
          </div>
          <pre className="pane">{span.text}</pre>
        </div>
      )}

      {spec && (
        <div className="bin stack">
          <div className="section-head cluster">
            <h3>Parameters accepted by {spec.name}</h3>
            <span className="count">{Object.keys(spec.params).length}</span>
          </div>
          <div className="paper">
            <h4>{spec.name}</h4>
            <dl>
              {Object.entries(spec.params).map(([key, p]) => (
                <div key={key}><dt>{key}</dt><dd>{p.type}{p.required ? ', required' : ''}{p.default !== undefined ? `, default ${String(p.default)}` : ''}</dd></div>
              ))}
            </dl>
          </div>
        </div>
      )}

      <div className="trace stack">
        <div className="section-head cluster">
          <h3>HTTP trace</h3>
          <span className="count">every call this page made, {api.traces.length}</span>
        </div>
        {api.traces.map((t) => (
          <details key={t.id}>
            <summary>
              <code>{t.method} {t.url}</code>
              <em>{t.status} · {t.ms} ms</em>
            </summary>
            <pre className="pane">{pretty({ request: t.request, status: t.status, response: t.response })}</pre>
          </details>
        ))}
      </div>
    </section>
  )
}
