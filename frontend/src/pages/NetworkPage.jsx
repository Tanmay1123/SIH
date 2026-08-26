import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import AlertsFeed from '../components/AlertsFeed.jsx'
import CompanyDetail from '../components/CompanyDetail.jsx'
import GraphView from '../components/GraphView.jsx'

/**
 * The investigation screen: the queue, the graph, and the evidence panel.
 *
 * This is the one page that genuinely wants all three panes at once - you read
 * an alert, see where it sits in the network, and decide. Everything that used
 * to share this screen without needing to (runs, reports, the ledger) now has
 * a page of its own.
 *
 * ?alert=<id> deep-links straight to one alert, which is how the Overview
 * queue and the Detections page hand off to here.
 */
export default function NetworkPage({
  graph,
  rings,
  selectedRing,
  onSelectRing,
  selectedCompanyId,
  onSelectCompany,
  onClearCompany,
  onConfirm,
  onDismiss,
  reviewing,
  loading,
  ringMembersOnly,
  onToggleScope,
  alertsCollapsed,
  onToggleAlerts,
  theme,
  riskThreshold,
}) {
  const [params, setParams] = useSearchParams()
  const requested = params.get('alert')

  // Open whatever the URL asked for, once, then drop it so the address bar
  // does not keep re-selecting it as the officer works through the queue.
  useEffect(() => {
    if (!requested || !rings?.length) return
    const match = rings.find((r) => String(r.id) === String(requested))
    if (match && match.id !== selectedRing?.id) {
      onSelectRing(match)
      params.delete('alert')
      setParams(params, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested, rings])

  return (
    <div className="flex h-full min-h-0">
      <AlertsFeed
        rings={rings}
        selectedRingId={selectedRing?.id}
        onSelect={onSelectRing}
        loading={loading}
        collapsed={alertsCollapsed}
        onToggleCollapsed={onToggleAlerts}
        riskThreshold={riskThreshold}
      />

      <div className="min-w-0 flex-1">
        <GraphView
          graph={graph}
          selectedRing={selectedRing}
          onSelectCompany={onSelectCompany}
          loading={loading}
          ringMembersOnly={ringMembersOnly}
          onToggleScope={onToggleScope}
          theme={theme}
        />
      </div>

      <aside className="w-96 shrink-0 border-l border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <CompanyDetail
          ring={selectedRing}
          companyId={selectedCompanyId}
          onConfirm={onConfirm}
          onDismiss={onDismiss}
          onSelectCompany={onSelectCompany}
          onClearCompany={onClearCompany}
          reviewing={reviewing}
          riskThreshold={riskThreshold}
        />
      </aside>
    </div>
  )
}
