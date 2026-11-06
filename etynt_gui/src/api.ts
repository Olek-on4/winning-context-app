// The UI talks to the context service only through these calls. Paths are relative:
// the same server that serves this page serves /v1/*.

export type Status = 'VALID' | 'DEPRECATED' | 'DISPUTED' | 'PLANNED' | 'PROPOSED' | 'UNKNOWN'

export type Citation = { path: string; lines: [number, number]; hash?: string }

export type Claim = {
  statement: string
  status: Status
  valid_from: string | null
  valid_to: string | null
  confidence: number // 0..1
  superseded_by: string | null
  citations: Citation[]
  reason?: string
}

export type Conflict = { a: string; b: string; note: string }

export type Envelope = {
  answer: string
  claims: Claim[]
  not_valid?: Claim[] // present once the service splits by verdict itself
  conflicts: Conflict[]
  gaps: string[]
  degraded: boolean
  truncated?: boolean
}

export type Plan = {
  intent: string
  anchors: { kind: string; key: string; match: string }[]
  traverse: { predicates: string[]; direction: string; max_hops: number; max_nodes: number }
  time: { as_of: string; status_in: string[] }
  evidence: { min_confidence: number }
  output: { token_budget: number }
}

async function call<T>(input: string, init: RequestInit, as: 'json' | 'text' = 'json'): Promise<T> {
  const response = await fetch(input, init)
  if (!response.ok) {
    let detail = ''
    try {
      detail = (await response.json()).detail ?? ''
    } catch {
      /* body was not JSON */
    }
    throw new Error(detail || `The service answered ${response.status}.`)
  }
  return (as === 'json' ? response.json() : response.text()) as Promise<T>
}

const post = (body: unknown, signal?: AbortSignal): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
  signal,
})

export const query = (question: string, asOf: string | null, signal?: AbortSignal) =>
  call<Envelope>('/v1/query', post({ question, as_of: asOf || null }, signal))

export const plan = (question: string, signal?: AbortSignal) =>
  call<Plan>('/v1/plan', post({ question }, signal))

export const span = (c: Citation, signal?: AbortSignal) => {
  const params = new URLSearchParams({ path: c.path, start: String(c.lines[0]), end: String(c.lines[1]) })
  return call<string>(`/v1/span?${params}`, { signal }, 'text')
}

export const healthy = async () => {
  try {
    return (await fetch('/healthz', { cache: 'no-store' })).ok
  } catch {
    return false
  }
}

// Mirrors the service's own rule (ADR-0007): an agent may use a claim only if it is
// VALID and at least this confident. Used until the envelope carries `not_valid`.
export const MIN_CONFIDENCE = 0.4

export function split(envelope: Envelope): { current: Claim[]; notValid: Claim[] } {
  if (envelope.not_valid) return { current: envelope.claims, notValid: envelope.not_valid }
  const current: Claim[] = []
  const notValid: Claim[] = []
  for (const claim of envelope.claims) {
    if (claim.status === 'VALID' && claim.confidence >= MIN_CONFIDENCE) current.push(claim)
    else notValid.push(claim)
  }
  return { current, notValid }
}

export function whyNotValid(claim: Claim): string {
  if (claim.reason) return claim.reason
  switch (claim.status) {
    case 'VALID':
      return `Evidence too weak: ${pct(claim.confidence)} is below the ${pct(MIN_CONFIDENCE)} threshold.`
    case 'DEPRECATED':
      return claim.superseded_by
        ? `No longer true. Superseded by ${claim.superseded_by}${claim.valid_to ? ` on ${claim.valid_to}` : ''}.`
        : `No longer true${claim.valid_to ? ` since ${claim.valid_to}` : ''}.`
    case 'DISPUTED':
      return 'Sources disagree and none of them wins clearly.'
    case 'PLANNED':
      return 'Planned or target state, not implemented yet.'
    case 'PROPOSED':
      return 'Proposed, not decided.'
    default:
      return 'Not enough evidence to say either way.'
  }
}

export const pct = (x: number) => `${Math.round(x * 100)}%`
