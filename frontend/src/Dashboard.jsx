import { useCallback, useEffect, useRef, useState } from 'react'
import AlertsFeed from './components/AlertsFeed.jsx'
import CompanyDetail from './components/CompanyDetail.jsx'
import GraphView from './components/GraphView.jsx'
import LedgerViewer from './components/LedgerViewer.jsx'
import { CloseIcon, FileIcon, MoonIcon, SunIcon, TrashIcon, UploadIcon } from './icons.jsx'
import {
  clearToken,
  confirmRing,
  getGraph,
  getRing,
  getRings,
  getStatus,
  logout,
  runFullPipeline,
  uploadDataset,
} from './api'

/**
 * The whole fraud-investigation console on one page:
 *   left   - ranked alerts feed (the work queue), collapsible
 *   centre - network explorer, or the audit ledger
 *   right  - evidence panel for the selected ring or company
 */

function StatCard({ label, value, tone = 'default' }) {
  const tones = {
    default: 'text-zinc-800 dark:text-zinc-200',
    danger: 'text-red-600 dark:text-red-400',
    good: 'text-green-600 dark:text-green-400',
  }
  return (
    <div className="px-3">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`text-lg font-semibold ${tones[tone]}`}>{value}</div>
    </div>
  )
}

function ThemeToggle({ theme, onToggle }) {
  return (
    <button
      onClick={onToggle}
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
    >
      {theme === 'dark' ? <SunIcon className="h-4 w-4" /> : <MoonIcon className="h-4 w-4" />}
    </button>
  )
}

function FileDropZone({ label, hint, file, onChange }) {
  const inputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)

  const takeFile = (fileList) => {
    const f = fileList?.[0]
    if (f) onChange(f)
  }

  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-zinc-700 dark:text-zinc-300">{label}</div>

      {!file ? (
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            takeFile(e.dataTransfer.files)
          }}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors ${
            dragOver
              ? 'border-green-500 bg-green-50 dark:bg-green-950/30'
              : 'border-zinc-300 hover:border-zinc-400 dark:border-zinc-700 dark:hover:border-zinc-600'
          }`}
        >
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400">
            <UploadIcon className="h-5 w-5" />
          </span>
          <span className="text-sm font-semibold text-green-700 dark:text-green-400">Upload File</span>
          <span className="text-[11px] leading-relaxed text-zinc-500">{hint}</span>
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => takeFile(e.target.files)}
          />
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3 rounded-xl bg-green-50 px-4 py-3 dark:bg-zinc-800">
          <span className="flex min-w-0 items-center gap-2 text-sm text-zinc-700 dark:text-zinc-200">
            <FileIcon className="h-4 w-4 shrink-0 text-green-700 dark:text-green-400" />
            <span className="truncate">{file.name}</span>
          </span>
          <button
            onClick={() => onChange(null)}
            aria-label={`Remove ${file.name}`}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-green-600 text-white hover:bg-green-500"
          >
            <TrashIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  )
}

function UploadDataset({ onUploaded }) {
  const [companiesFile, setCompaniesFile] = useState(null)
  const [invoicesFile, setInvoicesFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(false)

  const reset = () => {
    setCompaniesFile(null)
    setInvoicesFile(null)
    setError(null)
  }

  const handleUpload = async () => {
    if (!companiesFile || !invoicesFile) return
    setUploading(true)
    setError(null)
    try {
      await uploadDataset(companiesFile, invoicesFile)
      reset()
      setOpen(false)
      await onUploaded()
    } catch (e) {
      const errors = e?.response?.data?.errors
      setError(
        Array.isArray(errors) && errors.length
          ? errors.slice(0, 5).join(' · ')
          : e?.response?.data?.detail || e.message,
      )
    } finally {
      setUploading(false)
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded border border-zinc-300 px-3 py-2 text-sm text-zinc-700 hover:border-zinc-400 hover:text-zinc-900 dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-zinc-500 dark:hover:text-white"
      >
        Upload CSV
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl dark:bg-zinc-900">
            <div className="mb-5 flex items-start justify-between">
              <div>
                <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                  Upload dataset
                </h2>
                <p className="mt-1 text-xs text-zinc-500">
                  Replaces the whole dataset. Drag both CSVs in, or click to browse.
                </p>
              </div>
              <button
                onClick={() => {
                  setOpen(false)
                  reset()
                }}
                aria-label="Close"
                className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
              >
                <CloseIcon className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <FileDropZone
                label="Companies CSV"
                hint="gstin, pan, name, director_name, registered_address, registered_date, declared_turnover"
                file={companiesFile}
                onChange={setCompaniesFile}
              />
              <FileDropZone
                label="Invoices CSV"
                hint="seller_gstin, buyer_gstin, amount, date, goods_description, has_eway_bill"
                file={invoicesFile}
                onChange={setInvoicesFile}
              />
            </div>

            {error && <p className="mt-4 text-xs text-red-500 dark:text-red-400">{error}</p>}

            <button
              onClick={handleUpload}
              disabled={!companiesFile || !invoicesFile || uploading}
              className="mt-5 w-full rounded-lg bg-green-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-green-600 disabled:opacity-50"
            >
              {uploading ? 'Uploading…' : 'Upload and replace dataset'}
            </button>
          </div>
        </div>
      )}
    </>
  )
}

export default function Dashboard({ username, onLoggedOut, theme, onToggleTheme }) {
  const [status, setStatus] = useState(null)
  const [rings, setRings] = useState([])
  const [selectedRing, setSelectedRing] = useState(null)
  const [selectedCompanyId, setSelectedCompanyId] = useState(null)
  const [graph, setGraph] = useState(null)
  const [ringMembersOnly, setRingMembersOnly] = useState(true)
  const [alertsCollapsed, setAlertsCollapsed] = useState(false)

  const [tab, setTab] = useState('graph')
  const [running, setRunning] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [ledgerKey, setLedgerKey] = useState(0)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      const [statusData, ringData, graphData] = await Promise.all([
        getStatus(),
        getRings(),
        getGraph(ringMembersOnly),
      ])
      setStatus(statusData)
      setRings(ringData)
      setGraph(graphData)
    } catch (e) {
      setError(
        e?.response?.data?.detail ||
          `Cannot reach the API. Is the backend running? (${e.message})`,
      )
    } finally {
      setLoading(false)
    }
  }, [ringMembersOnly])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleRunPipeline = async () => {
    setRunning(true)
    setError(null)
    setSelectedRing(null)
    setSelectedCompanyId(null)
    try {
      await runFullPipeline()
      await refresh()
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setRunning(false)
    }
  }

  const handleSelectRing = async (ring) => {
    setSelectedCompanyId(null)
    setTab('graph')
    try {
      setSelectedRing(await getRing(ring.id))
    } catch (e) {
      setError(e.message)
    }
  }

  const handleConfirm = async (ringId) => {
    setConfirming(true)
    try {
      await confirmRing(ringId)
      setSelectedRing(await getRing(ringId))
      setRings(await getRings())
      setStatus(await getStatus())
      setLedgerKey((k) => k + 1)
      setTab('ledger')
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setConfirming(false)
    }
  }

  const handleLogout = async () => {
    try {
      await logout()
    } catch {
      // Token may already be invalid server-side - fall through and clear it locally anyway.
    }
    clearToken()
    onLoggedOut()
  }

  const ledgerValid = status?.ledger?.valid
  const hasData = (status?.companies ?? 0) > 0
  const dash = '—'

  return (
    <div className="flex h-screen flex-col bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-200">
      {/* ---------------- header ---------------- */}
      <header className="flex items-center gap-4 border-b border-zinc-200 px-5 py-3 dark:border-zinc-800">
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />

        <div>
          <h1 className="text-base font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            GST Circular-Trade Fraud Detection
          </h1>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-600">
            {status?.companies
              ? `${status.companies} companies, ${status.invoices} invoices loaded`
              : 'No dataset loaded — upload one to begin'}
          </p>
        </div>

        <div className="ml-auto flex items-center divide-x divide-zinc-200 dark:divide-zinc-800">
          <StatCard label="Companies" value={status?.companies ?? dash} />
          <StatCard label="Invoices" value={status?.invoices ?? dash} />
          <StatCard label="Loops found" value={status?.rings_detected ?? dash} />
          <StatCard
            label="High risk"
            value={status?.high_risk_rings ?? dash}
            tone="danger"
          />
          <StatCard
            label="Confirmed"
            value={status?.rings_confirmed ?? dash}
            tone="good"
          />
          <StatCard
            label="Ledger"
            value={ledgerValid === undefined ? dash : ledgerValid ? 'Intact' : 'BROKEN'}
            tone={ledgerValid === false ? 'danger' : 'good'}
          />
        </div>

        <UploadDataset onUploaded={refresh} />

        <button
          onClick={handleRunPipeline}
          disabled={running || !hasData}
          title={hasData ? undefined : 'Upload a dataset first'}
          className="rounded bg-green-700 px-4 py-2 text-sm font-medium text-white hover:bg-green-600 disabled:opacity-50"
        >
          {running ? 'Running...' : 'Run detection'}
        </button>

        <div className="flex items-center gap-2 border-l border-zinc-200 pl-4 dark:border-zinc-800">
          <span className="text-xs text-zinc-500">{username}</span>
          <button
            onClick={handleLogout}
            className="text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300"
          >
            Log out
          </button>
        </div>
      </header>

      {error && (
        <div className="border-b border-red-200 bg-red-50 px-5 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/60 dark:text-red-300">
          {error}
        </div>
      )}

      {/* ---------------- body ---------------- */}
      <div className="flex min-h-0 flex-1">
        <AlertsFeed
          rings={rings}
          selectedRingId={selectedRing?.id}
          onSelect={handleSelectRing}
          loading={loading}
          collapsed={alertsCollapsed}
          onToggleCollapsed={() => setAlertsCollapsed((v) => !v)}
        />

        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex gap-1 border-b border-zinc-200 px-3 py-1.5 dark:border-zinc-800">
            {[
              ['graph', 'Network'],
              ['ledger', 'Audit ledger'],
            ].map(([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`rounded px-3 py-1 text-xs ${
                  tab === key
                    ? 'bg-zinc-200 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100'
                    : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1">
            {tab === 'graph' ? (
              <GraphView
                graph={graph}
                selectedRing={selectedRing}
                onSelectCompany={setSelectedCompanyId}
                loading={loading}
                ringMembersOnly={ringMembersOnly}
                onToggleScope={() => setRingMembersOnly((v) => !v)}
                theme={theme}
              />
            ) : (
              <LedgerViewer refreshKey={ledgerKey} />
            )}
          </div>
        </main>

        <aside className="w-96 shrink-0 border-l border-zinc-200 dark:border-zinc-800">
          <CompanyDetail
            ring={selectedRing}
            companyId={selectedCompanyId}
            onConfirm={handleConfirm}
            onSelectCompany={setSelectedCompanyId}
            onClearCompany={() => setSelectedCompanyId(null)}
            confirming={confirming}
          />
        </aside>
      </div>
    </div>
  )
}
