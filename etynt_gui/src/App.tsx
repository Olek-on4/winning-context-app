import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import logo from './assets/mark.png'
import * as api from './api'
import type { Citation, Claim, Detail, Envelope, Plan } from './api'
import DeveloperView from './DeveloperView'
import './App.css'

type View = 'search' | 'history' | 'api'
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
const DETAILS: Detail[] = ['low', 'medium', 'high']

const loadHistory = (): string[] => {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]')
  } catch {
    return []
  }
}

const fromUrl = () => {
  const p = new URLSearchParams(window.location.search)
  const level = DETAILS.find((d) => d === p.get('detail')) ?? 'medium'
  return { q: p.get('q') ?? '', asOf: p.get('as_of') ?? '', detail: level as Detail }
}

// Read once at load: a shared link opens straight on its answer.
const initial = fromUrl()

function App() {
  const [query, setQuery] = useState(initial.q)
  const [asOf, setAsOf] = useState(initial.asOf)
  const [detail, setDetail] = useState<Detail>(initial.detail)
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
  const detailRef = useRef<Detail>(detail)
  detailRef.current = detail

  useEffect(() => {
    const check = () => api.healthy().then(setOnline)
    check()
    const id = window.setInterval(check, 30_000)
    return () => window.clearInterval(id)
  }, [])

  const run = useCallback(async (question: string, date: string, push = true, d?: Detail) => {
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
      const params = new URLSearchParams({ q, detail: d ?? detailRef.current })
      if (date) params.set('as_of', date)
      window.history.pushState(null, '', `?${params}`)
    }
    try {
      const envelope = await api.query(q, date || null, controller.signal, d ?? detailRef.current)
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
    if (initial.q) run(initial.q, initial.asOf, false, initial.detail)
    const onPop = () => {
      const { q, asOf: d, detail: level } = fromUrl()
      setQuery(q)
      setAsOf(d)
      setDetail(level)
      if (q) run(q, d, false, level)
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
  // A different level is a different answer: refetch rather than relabel.
  const changeDetail = (d: Detail) => {
    setDetail(d)
    const q = query.trim() || result?.question || ''
    if (!q) return
    const params = new URLSearchParams({ q, detail: d })
    if (asOf) params.set('as_of', asOf)
    window.history.replaceState(null, '', `?${params}`)
    run(q, asOf, false, d)
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

  const searchHome = view === 'search' && !loading && !error && !result

  return (
    <div className="app">
      <header className="topbar cluster push">
        <div className="cluster">
          <button className="menu-button" type="button" onClick={() => setNavOpen(!navOpen)} aria-label="Toggle navigation" aria-expanded={navOpen}>Menu</button>
          <button className="brand cluster" type="button" onClick={goHome} aria-label="Ety&T home">
            <img src={logo} alt="" />
            <span>ETY&amp;T</span>
          </button>
          <nav className="topnav cluster" aria-label="Workspace">
            <button className={`nav-link ${view === 'search' ? 'active' : ''}`} type="button" onClick={() => { setView('search'); setNavOpen(false) }}>Search</button>
            <button className={`nav-link ${view === 'history' ? 'active' : ''}`} type="button" onClick={() => { setView('history'); setNavOpen(false) }}>History</button>
            <button className={`nav-link ${view === 'api' ? 'active' : ''}`} type="button" onClick={() => { setView('api'); setNavOpen(false) }}>API</button>
          </nav>
        </div>
        <div className={`connection cluster ${online === false ? 'offline' : ''}`} role="status">
          <span className="connection-dot" aria-hidden="true" />
          {online === null ? 'checking' : online ? 'online' : 'offline'}
        </div>
      </header>

      <div className="body with-sidebar">
        <aside className={`rail stack ${navOpen ? 'open' : ''}`}>
          <nav className="stack rail-nav" aria-label="Views">
            <button className={`rail-link ${view === 'search' ? 'active' : ''}`} type="button" onClick={() => { setView('search'); setNavOpen(false) }}>Search</button>
            <button className={`rail-link ${view === 'history' ? 'active' : ''}`} type="button" onClick={() => { setView('history'); setNavOpen(false) }}>History {history.length > 0 && <em>{history.length}</em>}</button>
            <button className={`rail-link ${view === 'api' ? 'active' : ''}`} type="button" onClick={() => { setView('api'); setNavOpen(false) }}>API</button>
          </nav>

          <div className="stack">
            <p className="rail-label">Try a trap</p>
            <div className="stack">
              {EXAMPLES.map((q) => <button key={q} className="rail-example" type="button" onClick={() => ask(q)}>{q}</button>)}
            </div>
          </div>

          <div className="rail-foot">
            Answers come only from current, cited evidence. Stale claims are returned and labelled.
            <div>Press <kbd>/</kbd> to focus the question.</div>
          </div>
        </aside>

        <main className="main">
          <div className="center stack">
            {searchHome ? (
              <>
                <section className="home stack">
                  <h1>Every answer cites a line.</h1>
                  <p className="home-sub">A context service over engineering documents: time-stamped claims, each with a status and the exact lines it came from.</p>
                  <QueryBar {...{ query, setQuery, asOf, setAsOf, detail, changeDetail, submit, loading, input }} />
                  <div className="sky stack">
                    <p className="rail-label">Start with a question the corpus gets wrong</p>
                    <div>
                      {EXAMPLES.map((q, i) => (
                        <button key={q} className="sky-row" type="button" onClick={() => ask(q)}>
                          <i>{String(i + 1).padStart(2, '0')}</i>
                          <span>{q}</span>
                          <b>-&gt;</b>
                        </button>
                      ))}
                    </div>
                  </div>
                </section>
              </>
            ) : (
              <>
                <QueryBar {...{ query, setQuery, asOf, setAsOf, detail, changeDetail, submit, loading, input }} />
                <div aria-live="polite" aria-busy={loading}>
                  {view === 'api' ? (
                    <DeveloperView />
                  ) : view === 'history' ? (
                    <HistoryView items={history} onAsk={ask} onClear={() => { setHistory([]); localStorage.removeItem(HISTORY_KEY) }} />
                  ) : loading ? (
                    <LoadingState />
                  ) : error ? (
                    <ErrorState message={error} onRetry={() => run(query, asOf, false)} />
                  ) : result ? (
                    <Results result={result} tab={tab} onTab={setTab} onCitation={setCitation} />
                  ) : null}
                </div>
              </>
            )}
            <p className="foot">Ety&amp;T context service. Corpus: Northstar Equipment, read-only. Every citation resolves to the bytes it quotes.</p>
          </div>
        </main>
      </div>

      {citation && <EvidenceDrawer key={api.citationKey(citation)} citation={citation} onClose={() => setCitation(null)} />}
    </div>
  )
}

type QueryProps = {
  query: string
  setQuery: (v: string) => void
  asOf: string
  setAsOf: (v: string) => void
  detail: Detail
  changeDetail: (d: Detail) => void
  submit: (e: FormEvent<HTMLFormElement>) => void
  loading: boolean
  input: React.RefObject<HTMLInputElement | null>
}

function QueryBar({ query, setQuery, asOf, setAsOf, detail, changeDetail, submit, loading, input }: QueryProps) {
  return (
    <form className="query box stack" onSubmit={submit} role="search">
      <div className="query-main cluster">
        <input
          ref={input}
          className="query-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask about the system"
          aria-label="Question"
          autoFocus={!initial.q}
        />
        <button className="button" type="submit" disabled={!query.trim() || loading}>{loading ? 'Searching' : 'Search'}</button>
      </div>
      <div className="query-options cluster">
        <label className="field cluster">
          <span>as of</span>
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} aria-label="As of date (empty means today)" />
        </label>
        <div className="cluster">
          <span className="field">detail</span>
          <div className="segmented cluster" role="group" aria-label="Response detail">
            {DETAILS.map((level) => (
              <button key={level} type="button" className={detail === level ? 'active' : ''} aria-pressed={detail === level} onClick={() => detail !== level && changeDetail(level)}>{level}</button>
            ))}
          </div>
        </div>
        <span className="hint">low is the agent default; medium the API default</span>
      </div>
    </form>
  )
}

function LoadingState() {
  return (
    <section className="state box stack">
      <h2>Tracing evidence</h2>
      <p>Planning the query, reading the graph, and checking every citation against its file.</p>
      <div className="loading-bar"><i /></div>
    </section>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="state box stack error">
      <h2>Could not load evidence</h2>
      <p>{message}</p>
      <div><button className="button button-quiet" type="button" onClick={onRetry}>Try again</button></div>
    </section>
  )
}

function HistoryView({ items, onAsk, onClear }: { items: string[]; onAsk: (q: string) => void; onClear: () => void }) {
  return (
    <section className="section stack">
      <div className="section-head cluster push">
        <h3>Recent questions</h3>
        <span className="count">{items.length} stored in this browser</span>
      </div>
      {items.length === 0 ? <p className="muted">Questions you ask will appear here.</p> : (
        <>
          <div className="history stack">
            {items.map((q, i) => (
              <button className="history-row" type="button" key={q} onClick={() => onAsk(q)}>
                <i>{String(i + 1).padStart(2, '0')}</i>
                <span>{q}</span>
                <i>-&gt;</i>
              </button>
            ))}
          </div>
          <div><button className="button button-quiet button-small" type="button" onClick={onClear}>Clear history</button></div>
        </>
      )}
    </section>
  )
}

function Results({ result, tab, onTab, onCitation }: {
  result: Result
  tab: Tab
  onTab: (t: Tab) => void
  onCitation: (c: Citation) => void
}) {
  const { envelope, question, asOf } = result
  const { current, notValid } = api.split(envelope)
  const all = [...current, ...notValid]
  const passages = envelope.evidence ?? []
  const citations = new Set(all.flatMap((c) => c.citations.map(api.citationKey))).size
  const state = envelope.degraded
    ? { cls: 'degraded', title: 'DEGRADED', note: 'partial evidence only' }
    : current.length
      ? { cls: 'verified', title: 'VERIFIED', note: `${current.length} current claim${current.length > 1 ? 's' : ''}` }
      : { cls: 'unknown', title: 'NO VALID EVIDENCE', note: 'nothing current to rely on' }

  return (
    <article className="result stack">
      <header className="result-head cluster push">
        <div>
          <p className="result-where">{asOf ? `as of ${asOf}` : 'current reading'}</p>
          <h2>{question}</h2>
        </div>
        <div className={`verdict ${state.cls}`}><b>{state.title}</b><small>{state.note}</small></div>
      </header>

      <div className={`reading ${current.length ? '' : 'empty'}`}>
        <div className="reading-rule" aria-hidden="true" />
        <div className="stack">
          {current.length
            ? <p className="reading-text">{envelope.answer}</p>
            : <p className="reading-text">No valid, sufficiently supported claim answers this question. Below is what the sources say and why it cannot be relied on.</p>}
          <p className="meta cluster">
            <span><b>{current.length}</b> current</span><span className="sep">/</span>
            <span><b>{notValid.length}</b> not valid</span><span className="sep">/</span>
            <span><b>{citations}</b> citations</span><span className="sep">/</span>
            <span>detail <b>{envelope.detail}</b></span>
            {envelope.truncated && <><span className="sep">/</span><span>trimmed to budget</span></>}
          </p>
        </div>
      </div>

      <nav className="tabs cluster" role="tablist" aria-label="Result details">
        {(['evidence', 'sources', 'timeline', 'plan'] as const).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={`tab ${tab === t ? 'selected' : ''}`} onClick={() => onTab(t)}>
            {t === 'sources' ? `Sources (${citations})` : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>

      {tab === 'evidence' ? (
        <div className="result-body with-sidebar">
          <aside className="margin stack">
            <div className="paper">
              <h4>Reading this answer</h4>
              <p>A claim is current when its status is valid, its interval covers the reading date and its citations hash-match the files.</p>
              <p>Quoted passages carry no status: they are corpus text, not a verdict.</p>
            </div>
            {envelope.degraded && (
              <div className="paper warn">
                <h4>Degraded</h4>
                <p>Part of the pipeline was unavailable. Treat every line above as incomplete.</p>
              </div>
            )}
            {envelope.gaps.length > 0 && (
              <div className="paper warn">
                <h4>Evidence notes</h4>
                {envelope.gaps.map((g) => <p key={g}>{g}</p>)}
              </div>
            )}
            {envelope.conflicts.length > 0 && (
              <div className="paper conflict">
                <h4>Conflicts, {envelope.conflicts.length} unresolved</h4>
                {envelope.conflicts.map((c) => <p key={c.a + c.b}><b>{c.a}</b> vs <b>{c.b}</b>. {c.note}</p>)}
              </div>
            )}
            {envelope.plan && (
              <div className="paper">
                <h4>Executed plan</h4>
                <dl>
                  <div><dt>intent</dt><dd>{envelope.plan.intent}</dd></div>
                  <div><dt>effort</dt><dd>{envelope.plan.effort}</dd></div>
                  <div><dt>as of</dt><dd>{envelope.plan.as_of ?? 'now'}</dd></div>
                  <div><dt>budget</dt><dd>{envelope.plan.token_budget}</dd></div>
                </dl>
              </div>
            )}
          </aside>

          <div className="stack">
            <FindingSection title={current.length ? 'Current, cited claims' : 'No valid claims'} count={current.length} claims={current} onCitation={onCitation} />
            {notValid.length > 0 && (
              <FindingSection title="Stale, unproven or disputed" count={notValid.length} claims={notValid} onCitation={onCitation} warn />
            )}
            {passages.length > 0 && <Passages passages={passages} onCitation={onCitation} />}
          </div>
        </div>
      ) : tab === 'sources' ? (
        <SourceList claims={all} onCitation={onCitation} />
      ) : tab === 'timeline' ? (
        <Timeline claims={all} />
      ) : (
        <QueryPlan key={question} question={question} executed={envelope.plan} />
      )}
    </article>
  )
}

function FindingSection({ title, count, claims, onCitation, warn = false }: { title: string; count: number; claims: Claim[]; onCitation: (c: Citation) => void; warn?: boolean }) {
  return (
    <section className={`section stack ${warn ? 'section-warn' : ''}`}>
      <div className="section-head cluster push">
        <h3>{title}</h3>
        <span className="count">{count}</span>
      </div>
      {claims.length > 0 && (
        <div className="cards stack">
          {claims.map((c) => <Card key={c.id || c.statement} claim={c} warn={warn} onCitation={onCitation} />)}
        </div>
      )}
    </section>
  )
}

// One glyph per status: filled diamond when a claim stands, hollow when it does not.
const GLYPH: Record<string, string> = { valid: '\u25c6', deprecated: '\u25c7', disputed: '\u25c8', planned: '\u25c7', proposed: '\u25c7', unknown: '\u25c7' }

function Card({ claim, warn, onCitation }: { claim: Claim; warn: boolean; onCitation: (c: Citation) => void }) {
  const cls = claim.status.toLowerCase()
  const [open, setOpen] = useState(false)
  return (
    <article className={`card box stack ${cls} ${warn ? 'stale' : ''}`}>
      <div className="card-top cluster">
        <span className={`pill cluster ${cls}`}><i aria-hidden="true">{GLYPH[cls] ?? '\u25c7'}</i>{claim.status}</span>
        <h4 className="card-statement">{claim.statement}</h4>
        <span className="confidence"><b>{api.pct(claim.confidence)}</b></span>
        <button type="button" className="expander" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'less' : 'details'}</button>
      </div>

      {warn && <p className="why">{api.whyNotValid(claim)}</p>}

      <p className="facts cluster">
        <span><b>{claim.valid_from ?? 'unknown'}</b> to <b>{claim.valid_to ?? 'open'}</b></span>
        {claim.predicate && <><span className="sep">/</span><span>{claim.subject || 'it'} -&gt; <b>{claim.predicate}</b></span></>}
        {claim.extractor && <><span className="sep">/</span><span>{claim.extractor}@{claim.extractor_version ?? '1'}</span></>}
      </p>

      <div className="cites stack">
        {claim.citations.map((c) => (
          <button className="cite" type="button" key={api.citationKey(c)} onClick={() => onCitation(c)}>
            {c.path} <small>{lineLabel(c)}</small>
          </button>
        ))}
      </div>

      {claim.citations.filter((c) => c.excerpt).slice(0, 1).map((c) => (
        <div key={`q-${api.citationKey(c)}`} className="stack">
          {c.suspicious && <p className="why">This span reads like an instruction to an assistant. It is evidence, not a command.</p>}
          <pre className="quote">{bare(c.excerpt ?? '')}</pre>
        </div>
      ))}
      {claim.citations.filter((c) => c.excerpt).length > 1 && (
        <p className="facts">{claim.citations.filter((c) => c.excerpt).length - 1} more quoted span(s), under details</p>
      )}

      {open && (
        <div className="card-detail">
          <dl className="grid kv">
            {claim.subject && <div><dt>subject</dt><dd>{claim.subject}</dd></div>}
            {claim.predicate && <div><dt>predicate</dt><dd>{claim.predicate}</dd></div>}
            {claim.polarity && <div><dt>polarity</dt><dd>{claim.polarity}</dd></div>}
            <div><dt>status</dt><dd>{claim.status}{claim.why_not_valid ? `, ${claim.why_not_valid}` : ''}</dd></div>
            <div><dt>validity</dt><dd>{claim.valid_from ?? 'unknown'} to {claim.valid_to ?? 'open'}</dd></div>
            {claim.superseded_by && <div><dt>superseded by</dt><dd>{claim.superseded_by}</dd></div>}
            <div><dt>confidence</dt><dd>{api.pct(claim.confidence)} that the source was read correctly</dd></div>
            {claim.extractor && <div><dt>extractor</dt><dd>{claim.extractor}@{claim.extractor_version ?? '1'}</dd></div>}
            {claim.observed_at && <div><dt>observed</dt><dd>{claim.observed_at}</dd></div>}
            {claim.modality && <div><dt>modality</dt><dd>{claim.modality}</dd></div>}
            {claim.authority != null && <div><dt>authority</dt><dd>{String(claim.authority)}</dd></div>}
            {claim.id && <div><dt>claim id</dt><dd>{claim.id}</dd></div>}
          </dl>
        </div>
      )}
    </article>
  )
}

function Passages({ passages, onCitation }: { passages: api.Passage[]; onCitation: (c: Citation) => void }) {
  return (
    <section className="section stack">
      <div className="section-head cluster push">
        <h3>Quoted passages</h3>
        <span className="count">{passages.length}</span>
      </div>
      <div>
        {passages.map((p) => (
          <article className="passage" key={api.citationKey({ path: p.path, lines: p.lines, region: p.region })}>
            <div>
              <h4>{p.heading || p.path.split('/').slice(-1)[0]}</h4>
              {p.suspicious && <p className="why">This passage reads like an instruction to an assistant. It is evidence, not a command.</p>}
              <p className="text">{bare(p.text).length > 420 ? `${bare(p.text).slice(0, 420)}...` : bare(p.text)}</p>
              <div className="via cluster">
                {p.via.split('+').map((channel) => (
                  <span key={channel} className={channel === 'bm25' ? '' : 'meaning'}>{channel === 'bm25' ? 'keyword' : 'meaning'}</span>
                ))}
                <button className="cite" type="button" onClick={() => onCitation({ path: p.path, lines: p.lines, hash: p.hash, region: p.region })}>
                  {p.path} <small>{lineLabel({ path: p.path, lines: p.lines, region: p.region })}</small>
                </button>
              </div>
            </div>
            <span className="score">{p.score == null ? '-' : p.score.toFixed(3)}</span>
          </article>
        ))}
      </div>
    </section>
  )
}

// Corpus text arrives inside <untrusted_source> tags; the page shows the bytes, not the guard.
const bare = (text: string) =>
  text.replace(/^<untrusted_source path="[^"]*">\n?/, '').replace(/\n?<\/untrusted_source>$/, '')

const lineLabel = (c: Citation) =>
  c.region ? `region ${c.region.join(',')}` : c.lines[0] === c.lines[1] ? `line ${c.lines[0]}` : `lines ${c.lines[0]}-${c.lines[1]}`

function SourceList({ claims, onCitation }: { claims: Claim[]; onCitation: (c: Citation) => void }) {
  const byKey = new Map<string, { citation: Citation; statuses: Set<string> }>()
  for (const claim of claims) for (const c of claim.citations) {
    const key = api.citationKey(c)
    const entry = byKey.get(key) ?? { citation: c, statuses: new Set<string>() }
    entry.statuses.add(claim.status)
    byKey.set(key, entry)
  }
  return (
    <section className="section stack">
      <div className="section-head cluster push">
        <h3>Every span behind this answer</h3>
        <span className="count">{byKey.size}</span>
      </div>
      <div>
        {byKey.size === 0 ? <p className="muted">No citations.</p> : [...byKey.values()].map(({ citation, statuses }) => (
          <button className="source" type="button" key={api.citationKey(citation)} onClick={() => onCitation(citation)}>
            <span><code>{citation.path}</code><small>{lineLabel(citation)}, supports {[...statuses].join(', ')}</small></span>
            <b>-&gt;</b>
          </button>
        ))}
      </div>
    </section>
  )
}

function Timeline({ claims }: { claims: Claim[] }) {
  const events = claims
    .flatMap((c) => [
      ...(c.valid_from ? [{ date: c.valid_from, text: c.statement, note: `became ${c.status === 'VALID' ? 'true' : 'recorded'}, ${c.status}` }] : []),
      ...(c.valid_to ? [{ date: c.valid_to, text: c.statement, note: c.superseded_by ? `ended, superseded by ${c.superseded_by}` : 'ended' }] : []),
    ])
    .sort((a, b) => a.date.localeCompare(b.date))
  return (
    <section className="section stack">
      <div className="section-head cluster push">
        <h3>How the answer changed over time</h3>
        <span className="count">{events.length} events</span>
      </div>
      {events.length === 0 ? <p className="muted">None of these claims carries a date.</p> : (
        <div className="timeline stack">
          {events.map((e, i) => (
            <div className="timeline-row" key={`${e.date}-${i}`}>
              <time>{e.date}</time>
              <div><p>{e.text}</p><small>{e.note}</small></div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function QueryPlan({ question, executed }: { question: string; executed?: Envelope['plan'] }) {
  const [plan, setPlan] = useState<Plan | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    api.plan(question, controller.signal).then(setPlan).catch((e) => { if (!controller.signal.aborted) setError((e as Error).message) })
    return () => controller.abort()
  }, [question])
  return (
    <section className="section stack">
      <div className="section-head cluster push">
        <h3>How the question was translated</h3>
        <span className="count">the planner sees only your question</span>
      </div>
      {error ? <p className="muted">Plan preview unavailable: {error}</p> : !plan ? <p className="muted">Loading plan...</p> : (
        <div className="grid grid-2">
          <div className="paper">
            <h4>Preview, unexecuted</h4>
            <dl>
              <div><dt>intent</dt><dd>{plan.intent}</dd></div>
              <div><dt>anchors</dt><dd>{plan.anchors.length ? plan.anchors.map((a) => `${a.kind}:${a.key}`).join(', ') : 'none'}</dd></div>
              <div><dt>predicates</dt><dd>{plan.traverse.predicates.join(', ') || 'any'}</dd></div>
              <div><dt>hops</dt><dd>{plan.traverse.max_hops}</dd></div>
              <div><dt>as of</dt><dd>{plan.time.as_of}</dd></div>
              <div><dt>statuses</dt><dd>{plan.time.status_in.join(', ')}</dd></div>
              <div><dt>budget</dt><dd>{plan.output.token_budget}</dd></div>
            </dl>
          </div>
          <div className="paper">
            <h4>Executed for this answer</h4>
            {executed ? (
              <dl>
                <div><dt>intent</dt><dd>{executed.intent}</dd></div>
                <div><dt>effort</dt><dd>{executed.effort}</dd></div>
                <div><dt>as of</dt><dd>{executed.as_of ?? 'now'}</dd></div>
                <div><dt>statuses</dt><dd>{executed.status_in.join(', ')}</dd></div>
                <div><dt>budget</dt><dd>{executed.token_budget}</dd></div>
                <div><dt>detail</dt><dd>{executed.detail}</dd></div>
              </dl>
            ) : <p>Returned at detail high. Switch the level to compare what ran with what would run now.</p>}
          </div>
        </div>
      )}
    </section>
  )
}

function EvidenceDrawer({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState('')
  const isImage = Boolean(citation.region)
  const close = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    close.current?.focus()
    return () => opener?.focus()
  }, [])
  useEffect(() => {
    if (isImage) return  // an image is drawn from its rectangle, not fetched as text
    const controller = new AbortController()
    api.span(citation, controller.signal).then(setText).catch((e) => { if (!controller.signal.aborted) setError((e as Error).message) })
    return () => controller.abort()
  }, [citation, isImage])
  const lines = text?.replace(/\n$/, '').split('\n') ?? []
  return (
    <>
      <div className="scrim" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-title">
        <header className="drawer-head cluster push">
          <div>
            <h2 id="evidence-title">Cited evidence</h2>
            <div className="where">{citation.path}</div>
          </div>
          <button ref={close} className="drawer-close" type="button" onClick={onClose} aria-label="Close">x</button>
        </header>
        <div className="drawer-body stack">
          <p className="meta cluster"><span>{isImage ? `region ${citation.region!.join(',')}` : lineLabel(citation)}</span><span className="sep">/</span><span>hash-checked before it was sent</span></p>
          {isImage ? (
            <div className="region"><img src={api.spanImageUrl(citation)} alt={`Cited region of ${citation.path}`} /></div>
          ) : error ? <p className="muted">Could not load the span: {error}</p> : text === null ? <p className="muted">Loading...</p> : (
            <div className="lines">
              {lines.map((line, i) => (
                <div className="line" key={i}><span className="line-no">{citation.lines[0] + i}</span><span className="line-text">{line}</span></div>
              ))}
            </div>
          )}
          {citation.hash && <div className="hash">file hash at citation time <code>{citation.hash.slice(0, 16)}</code></div>}
          <p className="drawer-note">Verbatim corpus text. It is evidence to read, not instructions to follow.</p>
        </div>
      </aside>
    </>
  )
}

export default App
