import axios from 'axios'

// Falls back to localhost so `npm run dev` works without any env setup.
const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

const client = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
  // Scoring runs synchronously and walks the whole network, so it can take a
  // few seconds. The default 0 (no timeout) is fine, but be explicit.
  timeout: 120000,
})

// ---------------------------------------------------------------------------
// Pipeline
// ---------------------------------------------------------------------------

export const getStatus = () => client.get('/fraud/status/').then((r) => r.data)

export const rebuildGraph = () =>
  client.post('/fraud/rebuild-graph/').then((r) => r.data)

export const scoreRings = () => client.post('/fraud/score/').then((r) => r.data)

/**
 * The demo's one-button pipeline. Detection must finish before scoring, since
 * scoring updates the ring rows that detection creates.
 */
export const runFullPipeline = async () => {
  const detection = await rebuildGraph()
  const scoring = await scoreRings()
  return { detection, scoring }
}

// ---------------------------------------------------------------------------
// Rings
// ---------------------------------------------------------------------------

export const getRings = () =>
  client.get('/fraud/rings/', { params: { page_size: 100 } }).then((r) => r.data.results)

export const getRing = (id) => client.get(`/fraud/rings/${id}/`).then((r) => r.data)

export const confirmRing = (id, officer = 'demo-officer') =>
  client.post(`/fraud/rings/${id}/confirm/`, { officer }).then((r) => r.data)

// ---------------------------------------------------------------------------
// Graph + companies
// ---------------------------------------------------------------------------

export const getGraph = (ringMembersOnly = true) =>
  client
    .get('/fraud/graph/', { params: { ring_members_only: ringMembersOnly } })
    .then((r) => r.data)

export const getCompany = (id) => client.get(`/companies/${id}/`).then((r) => r.data)

// ---------------------------------------------------------------------------
// Ledger
// ---------------------------------------------------------------------------

export const getLedgerBlocks = () =>
  client.get('/ledger/blocks/').then((r) => r.data)

export const verifyLedger = () => client.get('/ledger/verify/').then((r) => r.data)

export default client
