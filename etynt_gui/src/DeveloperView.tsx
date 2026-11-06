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
    <div className="dev-citations">
      <div className="sidebar-label">CITATIONS — click to read the source bytes</div>
      {cited.slice(0, 8).map((c) => (
        <button key={`${c.path}:${c.lines[0]}:${c.statement}`} type="button" className="dev-cite" onClick={() => onSpan(c)}>
          <code>{c.path}:{c.lines[0]}–{c.lines[1]}</code>
          <span>{c.statement}</span>
        </button>
      ))}
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
    api.mcpTools().then(setTools).catch((e: Error) => setError(e.message))
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
    <section className="dev">
      <header className="dev-head">
        <h2>API &amp; MCP console</h2>
        <p>
          Each button posts to the running service. The endpoint, the parameters and the raw JSON
          answer are shown verbatim, and every REST call the page makes is listed underneath.
        </p>
      </header>

      <div className="dev-tools">
        {tools.map((t) => (
          <button
            key={t.name}
            type="button"
            className={`dev-tool ${t.name === name ? 'active' : ''}`}
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

      <div className="dev-form">
        {Object.entries(spec?.params ?? {})
          .filter(([, p]) => p.required || p.type !== 'array')
          .map(([key, p]) => (
            <label key={key} className="dev-field">
              <span>{key}{p.required ? ' *' : ''}</span>
              <input
                type={p.format === 'date' ? 'date' : 'text'}
                value={values[key] ?? ''}
                onChange={(e) => setValues({ ...values, [key]: e.target.value })}
                aria-label={key}
              />
            </label>
          ))}
        <button type="button" className="search-button" onClick={run} disabled={busy}>
          {busy ? 'Running…' : 'Run tool'}
        </button>
      </div>

      <div className="dev-exchange">
        <div className="dev-request">
          <div className="sidebar-label">REQUEST</div>
          <pre>{`POST /v1/mcp/${name}\n${pretty({ params: paramsFor(spec) })}`}</pre>
        </div>
        <div className="dev-response">
          <div className="sidebar-label">RESPONSE {call && <em>{call.result.claims ? `${(call.result.claims as unknown[]).length} claims` : 'span'}</em>}</div>
          {error ? <p className="dev-error">{error}</p> : <pre>{call ? pretty(call.result) : 'Run a tool to see its answer.'}</pre>}
        </div>
      </div>

      {call && call.tool !== 'resolve_span' && <Citations result={call.result} onSpan={readSpan} />}

      {span && (
        <div className="dev-span">
          <div className="sidebar-label">SOURCE BYTES · {span.path}</div>
          <pre>{span.text}</pre>
        </div>
      )}

      {spec && (
        <div className="dev-spec">
          <div className="sidebar-label">PARAMETERS ACCEPTED BY {spec.name}</div>
          <ul>
            {Object.entries(spec.params).map(([key, p]) => (
              <li key={key}>
                <code>{key}</code> {p.type}
                {p.required ? ' · required' : ''}
                {p.default !== undefined ? ` · default ${String(p.default)}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="dev-trace">
        <div className="sidebar-label">HTTP TRACE — every call this page made ({api.traces.length})</div>
        {api.traces.map((t) => (
          <details key={t.id}>
            <summary>
              <code>{t.method} {t.url}</code>
              <em>{t.status} · {t.ms} ms</em>
            </summary>
            <pre>{pretty({ request: t.request, status: t.status, response: t.response })}</pre>
          </details>
        ))}
      </div>
    </section>
  )
}
