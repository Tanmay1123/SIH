/**
 * The investigator's work queue: every detected loop, highest risk first.
 *
 * The ordering is the product. Cycle detection alone hands over ~30 candidate
 * loops with no priority; this list is what turns that into "start here".
 */

const formatInr = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`
  return `₹${n.toLocaleString('en-IN')}`
}

const riskBadge = (score) => {
  if (score >= 70) return 'bg-red-950 text-red-300 border-red-800'
  if (score >= 40) return 'bg-orange-950 text-orange-300 border-orange-800'
  if (score > 0) return 'bg-cyan-950 text-cyan-300 border-cyan-800'
  return 'bg-slate-800 text-slate-400 border-slate-700'
}

const riskLabel = (score) => {
  if (score >= 70) return 'HIGH'
  if (score >= 40) return 'ELEVATED'
  if (score > 0) return 'LOW'
  return 'UNSCORED'
}

export default function AlertsFeed({ rings, selectedRingId, onSelect, loading }) {
  const scored = rings.filter((r) => r.risk_score > 0)
  const highRisk = rings.filter((r) => r.risk_score >= 70)

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-800 px-4 py-3">
        <h2 className="text-sm font-semibold tracking-wide text-slate-200">
          ALERTS
        </h2>
        <p className="mt-0.5 text-xs text-slate-500">
          {rings.length} circular-trade loop{rings.length === 1 ? '' : 's'} detected
          {scored.length > 0 && ` · ${highRisk.length} high risk`}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <p className="px-4 py-6 text-sm text-slate-500">Loading alerts…</p>
        )}

        {!loading && rings.length === 0 && (
          <p className="px-4 py-6 text-sm text-slate-500">
            No rings yet. Click <span className="text-slate-300">Run detection</span> to
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
                className={`w-full border-b border-slate-800/70 px-4 py-3 text-left transition-colors ${
                  selected ? 'bg-slate-800' : 'hover:bg-slate-800/50'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-600">#{index + 1}</span>
                    <span className="text-sm font-medium text-slate-200">
                      Ring {ring.id}
                    </span>
                    {ring.officer_confirmed && (
                      <span className="rounded border border-emerald-800 bg-emerald-950 px-1.5 py-0.5 text-[10px] font-medium text-emerald-300">
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

                <div className="mt-1 flex gap-3 text-xs text-slate-500">
                  <span>{ring.ring_size} companies</span>
                  <span>{formatInr(ring.total_cycle_value)} circulating</span>
                </div>

                <p className="mt-1 truncate text-xs text-slate-600">
                  {(ring.company_names || []).join(' → ')}
                </p>
              </button>
            )
          })}
      </div>
    </div>
  )
}
