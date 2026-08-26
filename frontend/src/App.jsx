import { useCallback, useEffect, useState } from 'react'
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
} from 'react-router-dom'
import AppShell from './layout/AppShell.jsx'
import LabPage from './lab/LabPage.jsx'
import Login from './Login.jsx'
import DetectionsPage from './pages/DetectionsPage.jsx'
import LedgerPage from './pages/LedgerPage.jsx'
import NetworkPage from './pages/NetworkPage.jsx'
import OverviewPage from './pages/OverviewPage.jsx'
import ProfilePage from './pages/ProfilePage.jsx'
import ReportsPage from './pages/ReportsPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'
import TeamPage from './pages/TeamPage.jsx'
import { AuthProvider, useAuth } from './useAuth.jsx'
import { useTheme } from './useTheme.js'
import { Banner } from './components/ui.jsx'
import {
  confirmRing,
  dismissRing,
  getGraph,
  getRing,
  getRings,
  getStatus,
  runDetection,
} from './api'

/**
 * Routing and the shared investigation state.
 *
 * The status/alerts/graph triple is fetched once here rather than per page,
 * because three of the pages read from it and refetching on every navigation
 * would rebuild the Cytoscape graph each time - which is both slow and visibly
 * jarring, since the graph has a deliberate reveal animation.
 */

function AuthedApp({ theme, toggleTheme }) {
  const { can } = useAuth()

  const [status, setStatus] = useState(null)
  const [rings, setRings] = useState([])
  const [graph, setGraph] = useState(null)
  const [selectedRing, setSelectedRing] = useState(null)
  const [selectedCompanyId, setSelectedCompanyId] = useState(null)

  const [ringMembersOnly, setRingMembersOnly] = useState(true)
  const [alertsCollapsed, setAlertsCollapsed] = useState(false)
  const [running, setRunning] = useState(false)
  const [reviewing, setReviewing] = useState(false)
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

  const handleRunDetection = async (name = '') => {
    setRunning(true)
    setError(null)
    setSelectedRing(null)
    setSelectedCompanyId(null)
    try {
      await runDetection(name)
      await refresh()
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setRunning(false)
    }
  }

  const handleSelectRing = async (ring) => {
    setSelectedCompanyId(null)
    try {
      setSelectedRing(await getRing(ring.id))
    } catch (e) {
      setError(e.message)
    }
  }

  /** Both review actions refresh the same things: the alert, queue, counters, ledger. */
  const afterReview = async (ringId) => {
    const [ring, ringList, statusData] = await Promise.all([
      getRing(ringId),
      getRings(),
      getStatus(),
    ])
    setSelectedRing(ring)
    setRings(ringList)
    setStatus(statusData)
    setLedgerKey((k) => k + 1)
  }

  const handleConfirm = async (ringId) => {
    setReviewing(true)
    setError(null)
    try {
      await confirmRing(ringId)
      await afterReview(ringId)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setReviewing(false)
    }
  }

  const handleDismiss = async (ringId, reason, note) => {
    setReviewing(true)
    setError(null)
    try {
      await dismissRing(ringId, reason, note)
      await afterReview(ringId)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setReviewing(false)
    }
  }

  const threshold = status?.risk_threshold ?? 70

  return (
    <>
      {error && (
        <div className="fixed inset-x-0 top-0 z-[60] px-4 pt-3">
          <Banner tone="danger" className="mx-auto max-w-3xl shadow-lg">
            <span className="flex-1">{error}</span>
            <button
              onClick={() => setError(null)}
              className="shrink-0 font-semibold hover:underline"
            >
              Dismiss
            </button>
          </Banner>
        </div>
      )}

      <Routes>
        <Route
          element={
            <AppShell
              theme={theme}
              onToggleTheme={toggleTheme}
              status={status}
              onRefresh={refresh}
              pendingCount={status?.rings_pending ?? 0}
            />
          }
        >
          <Route
            index
            element={
              <OverviewPage
                status={status}
                rings={rings}
                loading={loading}
                running={running}
                onRunDetection={() => handleRunDetection('')}
              />
            }
          />
          <Route
            path="network"
            element={
              <NetworkPage
                graph={graph}
                rings={rings}
                selectedRing={selectedRing}
                onSelectRing={handleSelectRing}
                selectedCompanyId={selectedCompanyId}
                onSelectCompany={setSelectedCompanyId}
                onClearCompany={() => setSelectedCompanyId(null)}
                onConfirm={handleConfirm}
                onDismiss={handleDismiss}
                reviewing={reviewing}
                loading={loading}
                ringMembersOnly={ringMembersOnly}
                onToggleScope={() => setRingMembersOnly((v) => !v)}
                alertsCollapsed={alertsCollapsed}
                onToggleAlerts={() => setAlertsCollapsed((v) => !v)}
                theme={theme}
                riskThreshold={threshold}
              />
            }
          />
          <Route
            path="detections"
            element={<DetectionsPage status={status} onChanged={refresh} />}
          />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="ledger" element={<LedgerPage refreshKey={ledgerKey} />} />
          <Route
            path="team"
            element={can.can_view_team ? <TeamPage /> : <Navigate to="/" replace />}
          />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </>
  )
}

function Gate({ theme, toggleTheme }) {
  const { checking, isAuthenticated, refresh } = useAuth()

  if (checking) {
    return (
      <div className="flex h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        <span className="h-6 w-6 animate-spin rounded-full border-2 border-zinc-300 border-t-transparent dark:border-zinc-700" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Login onAuthenticated={refresh} />
  }

  return <AuthedApp theme={theme} toggleTheme={toggleTheme} />
}

export default function App() {
  // Applied at the top of the tree so the chosen theme is already in effect on
  // the login screen, before there is a console to render at all.
  const { theme, toggle: toggleTheme } = useTheme()

  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* The Dataset Lab sits outside the console on purpose: no nav rail,
              no dataset, no case, and no login required to fabricate test
              data. Everything else is behind the gate. */}
          <Route path="/lab" element={<LabPage theme={theme} onToggleTheme={toggleTheme} />} />
          <Route path="/*" element={<Gate theme={theme} toggleTheme={toggleTheme} />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
