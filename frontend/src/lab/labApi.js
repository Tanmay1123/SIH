import axios from 'axios'

import { getToken } from '../api'

/**
 * The lab talks to the API on its own.
 *
 * It deliberately does NOT reuse the console's client. That client redirects
 * to the login screen on any 401, which is right for a case file and wrong
 * here: the lab is usable signed out, and only `load` - pushing generated data
 * into the console - needs an account. A 401 from that one call is information
 * to show the user, not a session to tear down.
 */
const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

const client = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
  // Generating a thousand companies and running the real detector over them is
  // seconds of honest work, not a hung request.
  timeout: 180000,
})

client.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Token ${token}`
  return config
})

export const getLabPresets = () => client.get('/lab/presets/').then((r) => r.data)

export const previewDataset = (spec) =>
  client.post('/lab/preview/', { spec }).then((r) => r.data)

export const loadIntoConsole = (spec, name) =>
  client.post('/lab/load/', { spec, name }).then((r) => r.data)

/**
 * Download the generated files as a zip.
 *
 * Done through the same axios client rather than a plain link so the request
 * carries the spec as JSON and any auth header, then handed to the browser as
 * an object URL. The URL is revoked afterwards; leaving it alive pins the whole
 * blob in memory for the life of the tab.
 */
export async function downloadDataset(spec) {
  const response = await client.post('/lab/download/', { spec }, { responseType: 'blob' })

  const disposition = response.headers['content-disposition'] || ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : 'codenova-dataset.zip'

  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)

  return filename
}
