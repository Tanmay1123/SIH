import { MenuIcon } from '../icons.jsx'

/**
 * The investigator's work queue: every detected loop, highest risk first.
 *
 * The ordering is the product. Cycle detection alone hands over ~30 candidate
 * loops with no priority; this list is what turns that into "start here".
 *
 * Collapsible via the hamburger button in its own header, so it can be
 * folded away for more graph space and reopened from the same slim strip.
 */

const formatInr = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`
  return `₹${n.toLocaleString('en-IN')}`
}

const riskBadge = (score) => {
  if (score >= 70) return 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-800'
  if (score >= 40) return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800'
  if (score > 0) return 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800'
  return 'bg-zinc-100 text-zinc-500 border-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700'
}

const riskLabel = (score) => {
  if (score >= 70) return 'HIGH'
  if (score >= 40) return 'ELEVATED'
  if (score > 0) return 'LOW'
  return 'UNSCORED'
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

export default function AlertsFeed({ rings, selectedRingId, onSelect, loading, collapsed, onToggleCollapsed }) {
  if (collapsed) {
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center border-r border-zinc-200 py-3 dark:border-zinc-800">
        <CollapseToggle onClick={onToggleCollapsed} />
      </aside>
    )
  }

  const scored = rings.filter((r) => r.risk_score > 0)
  const highRisk = rings.filter((r) => r.risk_score >= 70)

  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-zinc-200 dark:border-zinc-800">
      <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <CollapseToggle onClick={onToggleCollapsed} />
        <div>
          <h2 className="text-sm font-semibold tracking-wide text-zinc-900 dark:text-zinc-200">
            ALERTS
          </h2>
          <p className="mt-0.5 text-xs text-zinc-500">
            {rings.length} circular-trade loop{rings.length === 1 ? '' : 's'} detected
            {scored.length > 0 && ` · ${highRisk.length} high risk`}
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <p className="px-4 py-6 text-sm text-zinc-500">Loading alerts…</p>
        )}

        {!loading && rings.length === 0 && (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No rings yet. Click{' '}
            <span className="text-zinc-800 dark:text-zinc-300">Run detection</span> to
            rebuild the graph and score it.
          </p>
        )}

        {!loading &&
          rings.map((ring, index) => {
            const selected = ring.id === selectedRingId
            return (
              <button
                key={ring.id}
                onClick={() => onSelect(ring)}
                className={`w-full border-b border-zinc-200/70 px-4 py-3 text-left transition-colors dark:border-zinc-800/70 ${
                  selected
                    ? 'bg-zinc-100 dark:bg-zinc-800'
                    : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-zinc-400 dark:text-zinc-600">#{index + 1}</span>
                    <span className="text-sm font-medium text-zinc-900 dark:text-zinc-200">
                      Ring {ring.id}
                    </span>
                    {ring.officer_confirmed && (
                      <span className="rounded border border-green-200 bg-green-50 px-1.5 py-0.5 text-[10px] font-medium text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-300">
                        CONFIRMED
                      </span>
                    )}
                  </div>
                  <span
                    className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${riskBadge(
                      ring.risk_score,
                    )}`}
                  >
                    {ring.risk_score > 0 ? ring.risk_score.toFixed(1) : riskLabel(0)}
                  </span>
                </div>

                <div className="mt-1 flex gap-3 text-xs text-zinc-500">
                  <span>{ring.ring_size} companies</span>
                  <span>{formatInr(ring.total_cycle_value)} circulating</span>
                </div>

                <p className="mt-1 truncate text-xs text-zinc-400 dark:text-zinc-600">
                  {(ring.company_names || []).join(' → ')}
                </p>
              </button>
            )
          })}
      </div>
    </aside>
  )
}
