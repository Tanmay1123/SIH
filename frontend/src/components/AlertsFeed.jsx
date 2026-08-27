import { useMemo, useState } from 'react'
import { HubIcon, LoopIcon, MenuIcon } from '../icons.jsx'

/**
 * The investigator's work queue: every detected pattern, highest risk first.
 *
 * The ordering is the product. Detection alone hands over a pile of candidates
 * with no priority; this list is what turns that into "start here".
 *
 * Two kinds of alert share the queue:
 *   ring - a closed invoice loop (classic circular trading)
 *   mill - a company selling to many buyers and buying from nobody. Not a
 *          loop at all, so cycle detection is blind to it, and it is the most
 *          common form of real GST fraud.
 *
 * Collapsible via the hamburger button in its own header, so it can be folded
 * away for more graph space and reopened from the same slim strip.
 */

const formatInr = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`
  return `₹${n.toLocaleString('en-IN')}`
}

const riskBadge = (score, threshold) => {
  if (score >= threshold) return 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-800'
  if (score >= threshold * 0.57) return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800'
  if (score > 0) return 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800'
  return 'bg-zinc-100 text-zinc-500 border-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700'
}

function CollapseToggle({ onClick }) {
  return (
    <button
      onClick={onClick}
      title="Toggle alerts panel"
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
    >
      <MenuIcon className="h-4 w-4" />
    </button>
  )
}

function StatusPill({ status }) {
  if (status === 'confirmed') {
    return (
      <span className="rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
        CONFIRMED
      </span>
    )
  }
  if (status === 'dismissed') {
    return (
      <span className="rounded border border-zinc-300 bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
        CLEARED
      </span>
    )
  }
  return null
}

const FILTERS = [
  ['pending', 'To review'],
  ['all', 'All'],
  ['confirmed', 'Confirmed'],
  ['dismissed', 'Cleared'],
]

export default function AlertsFeed({
  rings,
  selectedRingId,
  onSelect,
  loading,
  collapsed,
  onToggleCollapsed,
  riskThreshold = 70,
}) {
  const [filter, setFilter] = useState('pending')

  const counts = useMemo(
    () => ({
      all: rings.length,
      pending: rings.filter((r) => r.status === 'pending').length,
      confirmed: rings.filter((r) => r.status === 'confirmed').length,
      dismissed: rings.filter((r) => r.status === 'dismissed').length,
      highRisk: rings.filter((r) => r.risk_score >= riskThreshold).length,
      mills: rings.filter((r) => r.kind === 'mill').length,
    }),
    [rings, riskThreshold],
  )

  const visible = useMemo(
    () => (filter === 'all' ? rings : rings.filter((r) => r.status === filter)),
    [rings, filter],
  )

  // Collapsing is a desktop space-saving affordance. On small screens the feed
  // is a whole tab of its own, so a 40px stub would just be a dead strip -
  // `lg:` keeps the collapsed rail off phones entirely.
  if (collapsed) {
    return (
      <aside className="hidden w-10 shrink-0 flex-col items-center gap-3 border-r border-zinc-200 py-3 lg:flex dark:border-zinc-800">
        <CollapseToggle onClick={onToggleCollapsed} />
        {counts.pending > 0 && (
          <span
            title={`${counts.pending} alerts still to review`}
            className="rounded bg-red-600 px-1 py-0.5 text-[10px] font-semibold text-white"
          >
            {counts.pending}
          </span>
        )}
      </aside>
    )
  }

  return (
    <aside className="flex h-full w-full shrink-0 flex-col border-r border-zinc-200 lg:w-80 dark:border-zinc-800">
      <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div className="flex items-center gap-2">
          <span className="hidden lg:block">
            <CollapseToggle onClick={onToggleCollapsed} />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold tracking-wide text-zinc-900 dark:text-zinc-200">
              ALERTS
            </h2>
            <p className="mt-0.5 truncate text-xs text-zinc-500">
              {counts.all} found · {counts.highRisk} high risk
              {counts.mills > 0 && ` · ${counts.mills} mill${counts.mills === 1 ? '' : 's'}`}
            </p>
          </div>
        </div>

        <div className="mt-2.5 flex flex-wrap gap-1">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`rounded px-2 py-0.5 text-[11px] transition-colors ${
                filter === key
                  ? 'bg-zinc-800 text-white dark:bg-zinc-200 dark:text-zinc-900'
                  : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-700'
              }`}
            >
              {label} {counts[key === 'all' ? 'all' : key]}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && <p className="px-4 py-6 text-sm text-zinc-500">Loading alerts…</p>}

        {!loading && counts.all === 0 && (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No alerts yet. Click{' '}
            <span className="text-zinc-800 dark:text-zinc-300">Run detection</span> to
            search this dataset.
          </p>
        )}

        {!loading && counts.all > 0 && visible.length === 0 && (
          <p className="px-4 py-6 text-sm text-zinc-500">
            Nothing in this view.{' '}
            {filter === 'pending' && 'Every alert in this run has been reviewed.'}
          </p>
        )}

        {!loading &&
          visible.map((ring, index) => {
            const selected = ring.id === selectedRingId
            const isMill = ring.kind === 'mill'
            return (
              <button
                key={ring.id}
                onClick={() => onSelect(ring)}
                className={`w-full border-b border-zinc-200/70 px-4 py-3 text-left transition-colors dark:border-zinc-800/70 ${
                  selected
                    ? 'bg-zinc-100 dark:bg-zinc-800'
                    : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                } ${ring.status === 'dismissed' ? 'opacity-55' : ''}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <span className="text-xs text-zinc-400 dark:text-zinc-600">
                      #{index + 1}
                    </span>
                    <span
                      title={isMill ? 'Fake invoice mill' : 'Circular trade ring'}
                      className={isMill ? 'text-amber-600 dark:text-amber-400' : 'text-zinc-400 dark:text-zinc-500'}
                    >
                      {isMill ? <HubIcon className="h-3.5 w-3.5" /> : <LoopIcon className="h-3.5 w-3.5" />}
                    </span>
                    <span className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-200">
                      {isMill ? 'Mill' : 'Ring'} {ring.id}
                    </span>
                    <StatusPill status={ring.status} />
                  </div>
                  <span
                    className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${riskBadge(
                      ring.risk_score,
                      riskThreshold,
                    )}`}
                  >
                    {ring.risk_score > 0 ? ring.risk_score.toFixed(1) : 'UNSCORED'}
                  </span>
                </div>

                <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-zinc-500">
                  <span>
                    {isMill ? `${ring.ring_size - 1} buyers` : `${ring.ring_size} companies`}
                  </span>
                  <span>{formatInr(ring.total_cycle_value)}</span>
                </div>

                {ring.closure === 'control' && (
                  <span className="mt-1 inline-block rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-950/60 dark:text-amber-300">
                    closes via shared ownership
                  </span>
                )}

                <p className="mt-1 truncate text-xs text-zinc-400 dark:text-zinc-600">
                  {isMill
                    ? (ring.company_names || [])[0]
                    : (ring.company_names || []).join(' → ')}
                </p>

                {ring.status === 'dismissed' && ring.dismissal_reason_label && (
                  <p className="mt-1 truncate text-[11px] italic text-zinc-500">
                    Cleared: {ring.dismissal_reason_label}
                  </p>
                )}
              </button>
            )
          })}
      </div>
    </aside>
  )
}
