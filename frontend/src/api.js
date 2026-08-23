import axios from 'axios'

// Falls back to localhost so `npm run dev` works without any env setup.
const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

const TOKEN_KEY = 'codenova_auth_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

const client = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
  // Scoring runs synchronously and walks the whole network, so it can take a
  // few seconds. The default 0 (no timeout) is fine, but be explicit.
  timeout: 120000,
})

// Every request carries the officer's bearer token, if we have one.
client.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Token ${token}`
  return config
})

// A 401 means the token is missing, wrong, or was invalidated server-side
// (logout, or the account was removed) - drop it and force a fresh login.
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      clearToken()
      window.dispatchEvent(new Event('codenova:unauthorized'))
    }
    return Promise.reject(error)
  },
)

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export const login = (username, password) =>
  client.post('/auth/login/', { username, password }).then((r) => r.data)

export const logout = () => client.post('/auth/logout/').then((r) => r.data)

export const whoami = () => client.get('/auth/whoami/').then((r) => r.data)

// ---------------------------------------------------------------------------
// Dataset upload
// ---------------------------------------------------------------------------

export const uploadDataset = (companiesFile, invoicesFile) => {
  const form = new FormData()
  form.append('companies', companiesFile)
  form.append('invoices', invoicesFile)
  return client
    .post('/data/upload/', form, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((r) => r.data)
}

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

// The confirming officer is derived server-side from the auth token, not sent
// by the client - see fraud_engine/views.py:confirm_ring.
export const confirmRing = (id) => client.post(`/fraud/rings/${id}/confirm/`).then((r) => r.data)

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
