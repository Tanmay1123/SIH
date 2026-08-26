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
// The signed-in account, its role, and what it is allowed to do
// ---------------------------------------------------------------------------

/** Profile + role + a permissions map the UI reads to decide what to show. */
export const getProfile = () => client.get('/auth/me/').then((r) => r.data)

export const updateProfile = (patch) => client.patch('/auth/me/', patch).then((r) => r.data)

export const changePassword = (currentPassword, newPassword) =>
  client
    .post('/auth/change-password/', {
      current_password: currentPassword,
      new_password: newPassword,
    })
    .then((r) => r.data)

// ---------------------------------------------------------------------------
// The supervisor's view of the team
// ---------------------------------------------------------------------------

export const getTeam = () => client.get('/team/').then((r) => r.data)

export const getTeamActivity = (limit = 40) =>
  client.get('/team/activity/', { params: { limit } }).then((r) => r.data)

export const setMemberRole = (id, role) =>
  client.post(`/team/${id}/role/`, { role }).then((r) => r.data)

// ---------------------------------------------------------------------------
// Settings an administrator can change without touching .env
// ---------------------------------------------------------------------------

export const getSettings = () => client.get('/settings/').then((r) => r.data)

export const updateSettings = (patch) =>
  client.patch('/settings/update/', patch).then((r) => r.data)

// ---------------------------------------------------------------------------
// Datasets - every upload is kept; one is active at a time
// ---------------------------------------------------------------------------

export const uploadDataset = (companiesFile, invoicesFile, name = '') => {
  const form = new FormData()
  form.append('companies', companiesFile)
  form.append('invoices', invoicesFile)
  if (name) form.append('name', name)
  return client
    .post('/data/upload/', form, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((r) => r.data)
}

export const getDatasets = () => client.get('/datasets/').then((r) => r.data)

export const activateDataset = (id) =>
  client.post(`/datasets/${id}/activate/`).then((r) => r.data)

export const renameDataset = (id, name) =>
  client.patch(`/datasets/${id}/`, { name }).then((r) => r.data)

export const deleteDataset = (id) =>
  client.delete(`/datasets/${id}/delete/`).then((r) => r.data)

// ---------------------------------------------------------------------------
// Pipeline + detection runs
// ---------------------------------------------------------------------------

export const getStatus = (runId) =>
  client.get('/fraud/status/', { params: runId ? { run: runId } : {} }).then((r) => r.data)

/**
 * One call, one named run. Detection and scoring happen together server-side
 * and are stored as a single dated record, so previous runs stay intact.
 */
export const runDetection = (name = '', note = '') =>
  client.post('/fraud/run/', { name, note }).then((r) => r.data)

export const getRuns = (datasetId) =>
  client
    .get('/fraud/runs/', {
      params: { page_size: 100, ...(datasetId ? { dataset: datasetId } : {}) },
    })
    .then((r) => r.data.results)

export const deleteRun = (id) => client.delete(`/fraud/runs/${id}/delete/`).then((r) => r.data)

// ---------------------------------------------------------------------------
// Alerts (circular-trade rings and fake invoice mills)
// ---------------------------------------------------------------------------

export const getRings = (runId) =>
  client
    .get('/fraud/rings/', { params: { page_size: 200, ...(runId ? { run: runId } : {}) } })
    .then((r) => r.data.results)

export const getRing = (id) => client.get(`/fraud/rings/${id}/`).then((r) => r.data)

// The reviewing officer is derived server-side from the auth token, not sent
// by the client - see fraud_engine/views.py.
export const confirmRing = (id, note = '') =>
  client.post(`/fraud/rings/${id}/confirm/`, { note }).then((r) => r.data)

/** The other half of the loop: telling the system it got one wrong. */
export const dismissRing = (id, reason, note = '') =>
  client.post(`/fraud/rings/${id}/dismiss/`, { reason, note }).then((r) => r.data)

export const getDismissalReasons = () =>
  client.get('/fraud/dismissal-reasons/').then((r) => r.data)

// ---------------------------------------------------------------------------
// Case reports to the supervisor
// ---------------------------------------------------------------------------

export const getReports = () =>
  client.get('/reports/', { params: { page_size: 100 } }).then((r) => r.data.results)

export const getReport = (id) => client.get(`/reports/${id}/`).then((r) => r.data)

export const createReport = (runId, { title = '', send = true, recipients = [] } = {}) =>
  client.post(`/fraud/runs/${runId}/report/`, { title, send, recipients }).then((r) => r.data)

export const resendReport = (id) => client.post(`/reports/${id}/send/`).then((r) => r.data)

export const getMailStatus = () => client.get('/reports/mail-status/').then((r) => r.data)

// ---------------------------------------------------------------------------
// Graph + companies
// ---------------------------------------------------------------------------

export const getGraph = (ringMembersOnly = true, runId) =>
  client
    .get('/fraud/graph/', {
      params: { ring_members_only: ringMembersOnly, ...(runId ? { run: runId } : {}) },
    })
    .then((r) => r.data)

export const getCompany = (id) => client.get(`/companies/${id}/`).then((r) => r.data)

// ---------------------------------------------------------------------------
// Ledger
// ---------------------------------------------------------------------------

export const getLedgerBlocks = () =>
  client.get('/ledger/blocks/').then((r) => r.data)

export const verifyLedger = () => client.get('/ledger/verify/').then((r) => r.data)

export default client
