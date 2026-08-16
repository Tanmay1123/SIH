import { useCallback, useEffect, useState } from 'react'
import AlertsFeed from './components/AlertsFeed.jsx'
import CompanyDetail from './components/CompanyDetail.jsx'
import GraphView from './components/GraphView.jsx'
import LedgerViewer from './components/LedgerViewer.jsx'
import { confirmRing, getGraph, getRing, getRings, getStatus, runFullPipeline } from './api'

/**
 * The whole fraud-investigation console on one page:
 *   left   - ranked alerts feed (the work queue)
 *   centre - network explorer, or the audit ledger
 *   right  - evidence panel for the selected ring or company
 */

function StatCard({ label, value, tone = 'default' }) {
  const tones = {
    default: 'text-slate-200',
    danger: 'text-red-400',
    good: 'text-emerald-400',
  }
  return (
    <div className="px-3">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`text-lg font-semibold ${tones[tone]}`}>{value}</div>
    </div>
  )
}

export default function Dashboard() {
  const [status, setStatus] = useState(null)
  const [rings, setRings] = useState([])
  const [selectedRing, setSelectedRing] = useState(null)
  const [selectedCompanyId, setSelectedCompanyId] = useState(null)
  const [graph, setGraph] = useState(null)
  const [ringMembersOnly, setRingMembersOnly] = useState(true)

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
      await confirmRing(ringId, 'demo-officer')
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

  const ledgerValid = status?.ledger?.valid
  const dash = '—'

  return (
    <div className="flex h-screen flex-col bg-slate-950 text-slate-200">
      {/* ---------------- header ---------------- */}
      <header className="flex items-center gap-4 border-b border-slate-800 px-5 py-3">
        <div>
          <h1 className="text-base font-semibold tracking-tight">
            CodeNova
            <span className="ml-2 text-xs font-normal text-slate-500">
              GST Circular-Trade Fraud Detection
            </span>
          </h1>
          <p className="text-[10px] text-slate-600">
            Synthetic demonstration dataset {dash} not connected to live GSTN data
          </p>
        </div>

        <div className="ml-auto flex items-center divide-x divide-slate-800">
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

        <button
          onClick={handleRunPipeline}
          disabled={running}
          className="rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:opacity-50"
        >
          {running ? 'Running...' : 'Run detection'}
        </button>
      </header>

      {error && (
        <div className="border-b border-red-900 bg-red-950/60 px-5 py-2 text-xs text-red-300">
          {error}
        </div>
      )}

      {/* ---------------- body ---------------- */}
      <div className="flex min-h-0 flex-1">
        <aside className="w-80 shrink-0 border-r border-slate-800">
          <AlertsFeed
            rings={rings}
            selectedRingId={selectedRing?.id}
            onSelect={handleSelectRing}
            loading={loading}
          />
        </aside>

        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex gap-1 border-b border-slate-800 px-3 py-1.5">
            {[
              ['graph', 'Network'],
              ['ledger', 'Audit ledger'],
            ].map(([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`rounded px-3 py-1 text-xs ${
                  tab === key
                    ? 'bg-slate-800 text-slate-100'
                    : 'text-slate-500 hover:text-slate-300'
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
              />
            ) : (
              <LedgerViewer refreshKey={ledgerKey} />
            )}
          </div>
        </main>

        <aside className="w-96 shrink-0 border-l border-slate-800">
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
