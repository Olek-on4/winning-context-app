import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import logo from './assets/northstar-bookshelf.png'
import * as api from './api'
import type { Citation, Claim, Envelope, Plan } from './api'
import './App.css'

type View = 'search' | 'history'
type Tab = 'evidence' | 'sources' | 'timeline' | 'plan'
type Result = { question: string; asOf: string | null; envelope: Envelope }

// Questions with a known trap in the corpus: each shows a different way a source can be stale.
const EXAMPLES = [
  'Does inventory-service still use Redis?',
  'Does the users table have a status column?',
  'Is people SSO approved?',
  'Does the operations console write stock through the API gateway?',
  'Is the order lookup secure?',
]

const HISTORY_KEY = 'etyt.history'
const loadHistory = (): string[] => {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]')
  } catch {
    return []
  }
}

const fromUrl = () => {
  const p = new URLSearchParams(window.location.search)
  return { q: p.get('q') ?? '', asOf: p.get('as_of') ?? '' }
}

// Read once at load: a shared link opens straight on its answer.
const initial = fromUrl()

function App() {
  const [query, setQuery] = useState(initial.q)
  const [asOf, setAsOf] = useState(initial.asOf)
  const [result, setResult] = useState<Result | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState<View>('search')
  const [tab, setTab] = useState<Tab>('evidence')
  const [citation, setCitation] = useState<Citation | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [online, setOnline] = useState<boolean | null>(null)
  const [history, setHistory] = useState<string[]>(loadHistory)
  const inflight = useRef<AbortController | null>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const check = () => api.healthy().then(setOnline)
    check()
    const id = window.setInterval(check, 30_000)
    return () => window.clearInterval(id)
  }, [])

  const run = useCallback(async (question: string, date: string, push = true) => {
    const q = question.trim()
    if (!q) return
    inflight.current?.abort()
    const controller = new AbortController()
    inflight.current = controller
    setView('search')
    setNavOpen(false)
    setError('')
    setLoading(true)
    setTab('evidence')
    if (push) {
      const params = new URLSearchParams({ q })
      if (date) params.set('as_of', date)
      window.history.pushState(null, '', `?${params}`)
    }
    try {
      const envelope = await api.query(q, date || null, controller.signal)
      setResult({ question: q, asOf: date || null, envelope })
      setHistory((prev) => {
        const next = [q, ...prev.filter((h) => h !== q)].slice(0, 20)
        localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
        return next
      })
      setOnline(true)
    } catch (e) {
      if (controller.signal.aborted) return
      setResult(null)
      setError(e instanceof TypeError ? 'The context service is not reachable.' : (e as Error).message)
      if (e instanceof TypeError) setOnline(false)
    } finally {
      if (inflight.current === controller) setLoading(false)
    }
  }, [])

  // Open a shared link directly, and keep Back/Forward in step with the URL.
  useEffect(() => {
    // Fetching is the external system this effect syncs with.
    // oxlint-disable-next-line react/set-state-in-effect
    if (initial.q) run(initial.q, initial.asOf, false)
    const onPop = () => {
      const { q, asOf: d } = fromUrl()
      setQuery(q)
      setAsOf(d)
      if (q) run(q, d, false)
      else setResult(null)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [run])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setCitation(null)
      if (event.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        event.preventDefault()
        input.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const ask = (q: string) => {
    setQuery(q)
    run(q, asOf)
  }
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    run(query, asOf)
  }
  const goHome = () => {
    inflight.current?.abort()
    setLoading(false)
    setResult(null)
    setError('')
    setQuery('')
    setView('search')
    window.history.pushState(null, '', window.location.pathname)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="mobile-menu" type="button" onClick={() => setNavOpen(!navOpen)} aria-label="Toggle navigation" aria-expanded={navOpen}>☰</button>
        <a className="brand" href="/" onClick={(e) => { e.preventDefault(); goHome() }} aria-label="Ety&T home">
          <img src={logo} alt="" />
          <span>ETY<b>&amp;T</b></span>
        </a>
        <div className={`connection ${online === false ? 'offline' : ''}`} role="status">
          <span className="connection-dot" aria-hidden="true" />
          {online === null ? 'Checking service…' : online ? 'Service online' : 'Service offline'}
        </div>
      </header>

      <div className="workspace">
        <aside className={`sidebar ${navOpen ? 'sidebar-open' : ''}`}>
          <div className="sidebar-label">WORKSPACE</div>
          <nav aria-label="Workspace">
            <button className={`nav-item ${view === 'search' ? 'active' : ''}`} type="button" onClick={() => { setView('search'); setNavOpen(false) }}><span>⌕</span> Search</button>
            <button className={`nav-item ${view === 'history' ? 'active' : ''}`} type="button" onClick={() => { setView('history'); setNavOpen(false) }}><span>⌛</span> Query history {history.length > 0 && <em>{history.length}</em>}</button>
          </nav>
          <div className="sidebar-label sidebar-examples">TRY A TRAP</div>
          <nav aria-label="Example questions">
            {EXAMPLES.map((q) => <button key={q} className="nav-item nav-example" type="button" onClick={() => ask(q)}>{q}</button>)}
          </nav>
          <div className="sidebar-footer">
            <p><strong>Ety&amp;T</strong> answers only from current, cited evidence and tells you what is stale.</p>
            <small>Press <kbd>/</kbd> to search</small>
          </div>
        </aside>

        <main className="canvas">
          <form className={`query-form ${result && !loading ? 'query-received' : ''} ${loading ? 'query-loading' : ''}`} onSubmit={submit} role="search">
            <span className="query-icon" aria-hidden="true">⌕</span>
            <input ref={input} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ask about the system… e.g. does inventory still use Redis?" aria-label="Question" autoFocus={!initial.q} />
            {query && <button className="clear-button" type="button" onClick={() => { setQuery(''); input.current?.focus() }} aria-label="Clear question">×</button>}
            <label className="as-of" title="Answer as the evidence stood on this date">
              <span>as of</span>
              <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} aria-label="As of date (empty means today)" />
            </label>
            <button className="search-button" type="submit" disabled={!query.trim() || loading}>{loading ? 'Searching…' : <>Search <span>↵</span></>}</button>
          </form>

          <div aria-live="polite" aria-busy={loading}>
            {view === 'history' ? (
              <HistoryView items={history} onAsk={ask} onClear={() => { setHistory([]); localStorage.removeItem(HISTORY_KEY) }} />
            ) : loading ? (
              <LoadingState />
            ) : error ? (
              <ErrorState message={error} onRetry={() => run(query, asOf, false)} />
            ) : !result ? (
              <EmptyState onAsk={ask} />
            ) : (
              <Results result={result} tab={tab} onTab={setTab} onCitation={setCitation} />
            )}
          </div>
        </main>
      </div>

      {citation && <EvidenceDrawer key={`${citation.path}:${citation.lines[0]}`} citation={citation} onClose={() => setCitation(null)} />}
    </div>
  )
}

function EmptyState({ onAsk }: { onAsk: (q: string) => void }) {
  return (
    <section className="empty-state">
      <img src={logo} alt="" />
      <p className="eyebrow">EVIDENCE WORKSPACE</p>
      <h1>What is true in the system<br />right now?</h1>
      <p className="empty-copy">Every answer separates current, cited facts from stale or unproven ones,<br />and links each to the exact lines it came from.</p>
      <div className="example-questions">
        <span>Start with a question the docs get wrong</span>
        {EXAMPLES.slice(0, 3).map((q) => <button key={q} type="button" onClick={() => onAsk(q)}>{q}<b>→</b></button>)}
      </div>
    </section>
  )
}

function LoadingState() {
  return (
    <section className="loading-state">
      <p className="eyebrow">WORKING</p>
      <h1>Tracing evidence…</h1>
      <p className="loading-note">Planning the query, reading the graph and checking every citation against its file.</p>
    </section>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="error-state">
      <span className="error-icon">⚠</span>
      <p className="eyebrow">REQUEST FAILED</p>
      <h1>Could not load evidence</h1>
      <p>{message}</p>
      <button type="button" onClick={onRetry}>Try again</button>
    </section>
  )
}

function HistoryView({ items, onAsk, onClear }: { items: string[]; onAsk: (q: string) => void; onClear: () => void }) {
  return (
    <section className="collection-view">
      <p className="eyebrow">QUERY HISTORY</p>
      <h1>Recent questions</h1>
      <p className="collection-description">{items.length ? 'Stored in this browser only.' : 'Questions you ask will appear here.'}</p>
      {items.length > 0 && (
        <>
          <div className="collection-list">
            {items.map((q) => <button type="button" key={q} onClick={() => onAsk(q)}><span className="collection-icon">⌛</span><span>{q}</span><b>→</b></button>)}
          </div>
          <button type="button" className="link-button" onClick={onClear}>Clear history</button>
        </>
      )}
    </section>
  )
}

function Results({ result, tab, onTab, onCitation }: { result: Result; tab: Tab; onTab: (t: Tab) => void; onCitation: (c: Citation) => void }) {
  const { envelope, question, asOf } = result
  const { current, notValid } = api.split(envelope)
  const all = [...current, ...notValid]
  const citations = new Set(all.flatMap((c) => c.citations.map((x) => `${x.path}:${x.lines[0]}`))).size
  const state = envelope.degraded
    ? { cls: 'degraded', icon: '!', title: 'DEGRADED', note: 'Partial evidence only' }
    : current.length
      ? { cls: 'verified', icon: '✓', title: 'VERIFIED', note: `${current.length} current claim${current.length > 1 ? 's' : ''}` }
      : { cls: 'unknown', icon: '?', title: 'NO VALID EVIDENCE', note: 'Nothing current to rely on' }

  return (
    <section className="results">
      <div className="result-heading">
        <div>
          <p className="eyebrow">{asOf ? `AS OF ${asOf}` : 'CURRENT READING'}</p>
          <h1>{question}</h1>
        </div>
        <div className={`result-state ${state.cls}`}><span>{state.icon}</span><div><strong>{state.title}</strong><small>{state.note}</small></div></div>
      </div>

      <article className={`answer-card ${current.length ? '' : 'answer-empty'}`}>
        <div className="answer-mark">{current.length ? '✓' : '?'}</div>
        <div className="answer-content">
          <p className="eyebrow">{current.length ? 'ANSWER FROM CURRENT EVIDENCE' : 'NO CURRENT EVIDENCE'}</p>
          <p className="answer-text">{current.length ? envelope.answer : 'There is no valid, sufficiently supported claim for this question. See below for what the sources say and why it is not reliable.'}</p>
          <div className="answer-meta">
            <span>{current.length} current</span><i /><span>{notValid.length} not valid</span><i /><span>{citations} citations</span>
            {envelope.truncated && <><i /><span>trimmed to fit the token budget</span></>}
          </div>
        </div>
      </article>

      {envelope.degraded && (
        <div className="notes-tray"><span className="notes-icon">⚠</span><div><p className="eyebrow">DEGRADED ANSWER</p><p>Part of the pipeline was unavailable. Treat this answer as incomplete; details are under evidence notes.</p></div></div>
      )}

      <div className="result-tabs" role="tablist" aria-label="Result details">
        {([['evidence', 'Evidence'], ['sources', `Sources (${citations})`], ['timeline', 'Timeline'], ['plan', 'Query plan']] as const).map(([t, label]) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? 'selected' : ''} onClick={() => onTab(t)}>{label}</button>
        ))}
      </div>

      {tab === 'evidence' && (
        <>
          <ClaimSection eyebrow="CURRENT — SAFE TO USE" title={current.length ? 'Valid, cited claims' : 'No valid claims'} claims={current} onCitation={onCitation} />
          {notValid.length > 0 && (
            <ClaimSection eyebrow="NOT VALID — DO NOT RELY ON" title="What the sources say that is stale, unproven or disputed" claims={notValid} onCitation={onCitation} warn />
          )}
          {envelope.gaps.length > 0 && (
            <div className="notes-tray"><span className="notes-icon">⚠</span><div><p className="eyebrow">EVIDENCE NOTES</p>{envelope.gaps.map((g) => <p key={g}>{g}</p>)}</div></div>
          )}
          {envelope.conflicts.length > 0 && (
            <div className="conflicts-panel">
              <div className="conflict-heading"><span>⇄</span><div><p className="eyebrow">CONFLICTS</p><h2>{envelope.conflicts.length} unresolved</h2></div></div>
              {envelope.conflicts.map((c) => <p className="conflict-row" key={c.a + c.b}><b>{c.a}</b> vs <b>{c.b}</b><small>{c.note}</small></p>)}
            </div>
          )}
        </>
      )}
      {tab === 'sources' && <SourceList claims={all} onCitation={onCitation} />}
      {tab === 'timeline' && <Timeline claims={all} />}
      {tab === 'plan' && <QueryPlan key={question} question={question} />}
    </section>
  )
}

function ClaimSection({ eyebrow, title, claims, onCitation, warn = false }: { eyebrow: string; title: string; claims: Claim[]; onCitation: (c: Citation) => void; warn?: boolean }) {
  return (
    <>
      <div className={`section-heading ${warn ? 'section-warn' : ''}`}><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div></div>
      {claims.length > 0 && <div className="claims-grid">{claims.map((c) => <ClaimCard key={c.statement + c.status} claim={c} warn={warn} onCitation={onCitation} />)}</div>}
    </>
  )
}

const ICONS: Record<string, string> = { valid: '✓', deprecated: '◌', disputed: '⇄', planned: '◷', proposed: '◇', unknown: '?' }

function ClaimCard({ claim, warn, onCitation }: { claim: Claim; warn: boolean; onCitation: (c: Citation) => void }) {
  const cls = claim.status.toLowerCase()
  return (
    <article className={`claim-card ${cls}`}>
      <div className="claim-topline"><span className="status-pill"><b>{ICONS[cls] ?? '◇'}</b> {claim.status}</span></div>
      <h3>{claim.statement}</h3>
      {warn && <p className="why">{api.whyNotValid(claim)}</p>}
      <div className="confidence"><span>Confidence</span><strong>{api.pct(claim.confidence)}</strong><div className="confidence-track"><i style={{ width: api.pct(claim.confidence) }} /></div></div>
      <div className="date-row"><span>Valid from</span><b>{claim.valid_from ?? 'unknown'}</b>{claim.valid_to && <><span>until</span><b>{claim.valid_to}</b></>}</div>
      <div className="citations">
        {claim.citations.map((c) => (
          <button type="button" key={`${c.path}:${c.lines[0]}`} onClick={() => onCitation(c)}>
            <span>▣</span><span>{c.path} <small>· {lineLabel(c)}</small></span><b>↗</b>
          </button>
        ))}
      </div>
    </article>
  )
}

const lineLabel = (c: Citation) => (c.lines[0] === c.lines[1] ? `line ${c.lines[0]}` : `lines ${c.lines[0]}–${c.lines[1]}`)

function SourceList({ claims, onCitation }: { claims: Claim[]; onCitation: (c: Citation) => void }) {
  const byPath = new Map<string, { citation: Citation; statuses: Set<string> }>()
  for (const claim of claims) for (const c of claim.citations) {
    const key = `${c.path}:${c.lines[0]}`
    const entry = byPath.get(key) ?? { citation: c, statuses: new Set<string>() }
    entry.statuses.add(claim.status)
    byPath.set(key, entry)
  }
  return (
    <section className="detail-panel">
      <p className="eyebrow">CONTRIBUTING SOURCES</p>
      <h2>Every span behind this answer</h2>
      {byPath.size === 0 ? <p className="muted">No citations.</p> : (
        <div className="source-list">
          {[...byPath.values()].map(({ citation, statuses }) => (
            <button type="button" key={`${citation.path}:${citation.lines[0]}`} onClick={() => onCitation(citation)}>
              <span>▣</span><span><b>{citation.path}</b><small>{lineLabel(citation)} · supports {[...statuses].join(', ')}</small></span><i>↗</i>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}

function Timeline({ claims }: { claims: Claim[] }) {
  const events = claims
    .flatMap((c) => [
      ...(c.valid_from ? [{ date: c.valid_from, text: `${c.statement}`, note: `became ${c.status === 'VALID' ? 'true' : 'recorded'} · ${c.status}`, tone: c.status === 'VALID' ? 'green' : 'amber' }] : []),
      ...(c.valid_to ? [{ date: c.valid_to, text: c.statement, note: c.superseded_by ? `ended · superseded by ${c.superseded_by}` : 'ended', tone: 'amber' }] : []),
    ])
    .sort((a, b) => a.date.localeCompare(b.date))
  return (
    <section className="detail-panel">
      <p className="eyebrow">TIMELINE</p>
      <h2>How the answer changed over time</h2>
      {events.length === 0 ? <p className="muted">None of these claims carries a date.</p> : (
        <div className="timeline">
          {events.map((e, i) => <div key={i}><span className={`timeline-dot ${e.tone}`} /><strong>{e.date}</strong><p>{e.text}</p><small>{e.note}</small></div>)}
        </div>
      )}
    </section>
  )
}

function QueryPlan({ question }: { question: string }) {
  const [plan, setPlan] = useState<Plan | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    api.plan(question, controller.signal).then(setPlan).catch((e) => { if (!controller.signal.aborted) setError((e as Error).message) })
    return () => controller.abort()
  }, [question])
  return (
    <section className="detail-panel">
      <p className="eyebrow">QUERY PLAN</p>
      <h2>How the question was translated</h2>
      <p className="muted">The planner sees only your question, never corpus text.</p>
      {error ? <p className="muted">Plan unavailable: {error}</p> : !plan ? <p className="muted">Loading plan…</p> : (
        <dl className="plan-grid">
          <dt>Intent</dt><dd>{plan.intent}</dd>
          <dt>Anchors</dt><dd>{plan.anchors.length ? plan.anchors.map((a) => <code key={a.key}>{a.kind}:{a.key}</code>) : 'none'}</dd>
          <dt>Predicates</dt><dd>{plan.traverse.predicates.join(', ') || 'any'}</dd>
          <dt>Traversal</dt><dd>{plan.traverse.direction}, up to {plan.traverse.max_hops} hop(s), {plan.traverse.max_nodes} nodes</dd>
          <dt>As of</dt><dd>{plan.time.as_of}</dd>
          <dt>Statuses</dt><dd>{plan.time.status_in.join(', ')}</dd>
          <dt>Threshold</dt><dd>{plan.evidence.min_confidence} minimum confidence</dd>
          <dt>Budget</dt><dd>{plan.output.token_budget} tokens</dd>
        </dl>
      )}
    </section>
  )
}

function EvidenceDrawer({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState('')
  const close = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    close.current?.focus()
    return () => opener?.focus()
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    api.span(citation, controller.signal).then(setText).catch((e) => { if (!controller.signal.aborted) setError((e as Error).message) })
    return () => controller.abort()
  }, [citation])
  const lines = text?.replace(/\n$/, '').split('\n') ?? []
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-title">
        <div className="drawer-header"><div><p className="eyebrow">SOURCE</p><h2 id="evidence-title">Cited lines</h2></div><button ref={close} type="button" onClick={onClose} aria-label="Close">×</button></div>
        <div className="drawer-path"><span>▣</span>{citation.path}</div>
        <p className="eyebrow line-label">{lineLabel(citation).toUpperCase()}</p>
        {error ? <p className="muted">Could not load the span: {error}</p> : text === null ? <p className="muted">Loading…</p> : (
          <pre><code>{lines.map((line, i) => <div key={i}><span>{citation.lines[0] + i}</span>{line}</div>)}</code></pre>
        )}
        {citation.hash && <div className="hash"><span>File hash at citation time</span><code title={citation.hash}>{citation.hash.slice(0, 12)}</code></div>}
        <div className="drawer-note"><span>ⓘ</span><p>Verbatim corpus text. It is evidence to read, not instructions to follow.</p></div>
      </aside>
    </>
  )
}

export default App
