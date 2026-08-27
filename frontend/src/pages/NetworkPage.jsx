import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import AlertsFeed from '../components/AlertsFeed.jsx'
import CompanyDetail from '../components/CompanyDetail.jsx'
import GraphView from '../components/GraphView.jsx'
import { cx } from '../components/ui.jsx'

const PANES = [
  ['queue', 'Queue'],
  ['graph', 'Graph'],
  ['evidence', 'Evidence'],
]

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

  // Which single pane a phone is showing. Ignored from `lg` up, where all
  // three are on screen at once - this page genuinely wants that, and the
  // tabs exist only because a 375px screen cannot give it.
  const [pane, setPane] = useState('queue')

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

  // Picking an alert on a phone should move you to the thing you picked it to
  // see. On desktop the evidence pane is already visible, so nothing moves.
  const handleSelectRing = (ring) => {
    onSelectRing(ring)
    setPane('evidence')
  }

  const handleSelectCompany = (id) => {
    onSelectCompany(id)
    setPane('evidence')
  }

  return (
    <div className="flex h-full min-h-0 flex-col lg:flex-row">
      {/* -------- pane switcher: small screens only -------- */}
      <div className="flex shrink-0 border-b border-zinc-200 bg-white lg:hidden dark:border-zinc-800 dark:bg-zinc-900">
        {PANES.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setPane(key)}
            aria-current={pane === key}
            className={cx(
              'relative flex-1 px-3 py-2.5 text-[13px] font-medium transition-colors',
              pane === key
                ? 'text-zinc-900 dark:text-zinc-100'
                : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300',
            )}
          >
            {label}
            {key === 'queue' && rings?.length > 0 && (
              <span className="ml-1.5 text-[11px] text-zinc-400">{rings.length}</span>
            )}
            {pane === key && (
              <span className="absolute inset-x-0 bottom-0 h-0.5 bg-brand-500" />
            )}
          </button>
        ))}
      </div>

      <div className="flex min-h-0 flex-1 lg:contents">
        <div className={cx('min-h-0 w-full lg:block lg:w-auto', pane === 'queue' ? 'block' : 'hidden')}>
          <AlertsFeed
            rings={rings}
            selectedRingId={selectedRing?.id}
            onSelect={handleSelectRing}
            loading={loading}
            collapsed={alertsCollapsed}
            onToggleCollapsed={onToggleAlerts}
            riskThreshold={riskThreshold}
          />
        </div>

        <div className={cx('min-w-0 flex-1 lg:block', pane === 'graph' ? 'block' : 'hidden')}>
          <GraphView
            graph={graph}
            selectedRing={selectedRing}
            onSelectCompany={handleSelectCompany}
            loading={loading}
            ringMembersOnly={ringMembersOnly}
            onToggleScope={onToggleScope}
            theme={theme}
          />
        </div>

        <aside
          className={cx(
            'w-full shrink-0 overflow-y-auto border-l border-zinc-200 bg-white lg:block lg:w-96 dark:border-zinc-800 dark:bg-zinc-900',
            pane === 'evidence' ? 'block' : 'hidden',
          )}
        >
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
    </div>
  )
}
