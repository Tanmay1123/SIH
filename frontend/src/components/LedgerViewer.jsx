import { useEffect, useState } from 'react'
import { getLedgerBlocks, verifyLedger } from '../api'

/**
 * The audit trail.
 *
 * Every confirmed ring is one block. Showing each block's own hash next to the
 * previous hash it points at makes the chaining visible: the value in one row's
 * "links to" column is literally the hash in the row above. Break one and the
 * verification banner says which.
 */

const short = (hash) => (hash ? `${hash.slice(0, 16)}…${hash.slice(-8)}` : '—')

const formatInr = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`
  return `₹${n.toLocaleString('en-IN')}`
}

/**
 * The chain now carries three kinds of decision, not one. Each gets its own
 * one-line summary, because "Ring 425 · companies · risk 56" is what you get
 * from rendering a dismissal with the confirmation template.
 */
const RECORD_TYPES = {
  confirmed_fraud_ring: {
    label: 'CONFIRMED FRAUD',
    tone: 'border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300',
  },
  dismissed_alert: {
    label: 'CLEARED',
    tone: 'border-zinc-200 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400',
  },
  case_report_issued: {
    label: 'REPORT ISSUED',
    tone: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300',
  },
}

function BlockSummary({ payload }) {
  const type = payload?.record_type
  const cls = 'mt-1 text-[11px] text-zinc-600 dark:text-zinc-400'

  if (type === 'dismissed_alert') {
    return (
      <div className={cls}>
        {payload.pattern_kind === 'mill' ? 'Mill' : 'Ring'} {payload.ring_id} cleared as
        not fraud — {payload.reason} · risk {payload.risk_score} · by{' '}
        {payload.dismissed_by}
        {payload.note && (
          <span className="mt-0.5 block italic text-zinc-500">“{payload.note}”</span>
        )}
      </div>
    )
  }

  if (type === 'case_report_issued') {
    return (
      <div className={cls}>
        “{payload.title}” — {payload.confirmed_count ?? 0} confirmed,{' '}
        {formatInr(payload.confirmed_value)} at risk · issued by {payload.issued_by} to{' '}
        {(payload.recipients || []).length} recipient
        {(payload.recipients || []).length === 1 ? '' : 's'}
      </div>
    )
  }

  return (
    <div className={cls}>
      {payload?.pattern_kind === 'mill' ? 'Mill' : 'Ring'} {payload?.ring_id} ·{' '}
      {payload?.ring_size} companies · risk {payload?.risk_score} · confirmed by{' '}
      {payload?.confirmed_by}
      {payload?.closure === 'control' && (
        <span className="ml-1 text-amber-600 dark:text-amber-400">
          (closed by shared ownership)
        </span>
      )}
    </div>
  )
}

export default function LedgerViewer({ refreshKey }) {
  const [blocks, setBlocks] = useState([])
  const [chain, setChain] = useState(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([getLedgerBlocks(), verifyLedger()])
      .then(([b, v]) => {
        if (cancelled) return
        setBlocks(b)
        setChain(v)
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold tracking-wide text-zinc-900 dark:text-zinc-200">
            AUDIT LEDGER
          </h2>
          {chain && (
            <span
              className={`rounded border px-2 py-0.5 text-[11px] font-medium ${
                chain.valid
                  ? 'border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-300'
                  : 'border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300'
              }`}
            >
              {chain.valid ? 'CHAIN INTACT' : 'CHAIN BROKEN'}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-zinc-500">
          {chain?.message || 'Checking chain…'}
        </p>
        <p className="mt-1 text-[10px] leading-relaxed text-zinc-500 dark:text-zinc-600">
          A local SHA-256 hash chain — not a cryptocurrency. No wallet, no token,
          no gas fee, no public network. Each block hashes its own contents plus
          the previous block's hash, so editing any past record breaks every
          block after it.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && <p className="px-4 py-6 text-sm text-zinc-500">Loading ledger…</p>}

        {!loading && blocks.length === 0 && (
          <p className="px-4 py-6 text-sm text-zinc-500">
            The ledger is empty. Every officer decision — confirming an alert as
            fraud, clearing one as legitimate, or issuing a case report — is
            recorded here permanently.
          </p>
        )}

        {!loading &&
          blocks.map((block) => {
            const open = expanded === block.index
            return (
              <div key={block.index} className="border-b border-zinc-200/70 dark:border-zinc-800/70">
                <button
                  onClick={() => setExpanded(open ? null : block.index)}
                  className="w-full px-4 py-3 text-left hover:bg-zinc-100 dark:hover:bg-zinc-800/40"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2">
                      <span className="text-sm font-medium text-zinc-900 dark:text-zinc-200">
                        Block #{block.index}
                      </span>
                      {RECORD_TYPES[block.payload?.record_type] && (
                        <span
                          className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold ${
                            RECORD_TYPES[block.payload.record_type].tone
                          }`}
                        >
                          {RECORD_TYPES[block.payload.record_type].label}
                        </span>
                      )}
                    </span>
                    <span className="shrink-0 text-[11px] text-zinc-500">
                      {new Date(block.timestamp).toLocaleString('en-IN')}
                    </span>
                  </div>
                  <div className="mt-1 space-y-0.5 font-mono text-[10px]">
                    <div className="flex gap-2 text-zinc-500">
                      <span className="w-14 shrink-0">hash</span>
                      <span className="text-green-600 dark:text-green-400">{short(block.hash)}</span>
                    </div>
                    <div className="flex gap-2 text-zinc-500">
                      <span className="w-14 shrink-0">links to</span>
                      <span className="text-zinc-600 dark:text-zinc-400">{short(block.previous_hash)}</span>
                      {block.index === 0 && (
                        <span className="text-zinc-400 dark:text-zinc-600">(genesis)</span>
                      )}
                    </div>
                  </div>
                  <BlockSummary payload={block.payload} />

                  {block.payload?.model?.version && (
                    <div className="mt-1 font-mono text-[10px] text-zinc-400 dark:text-zinc-600">
                      model {block.payload.model.version} · threshold{' '}
                      {block.payload.model.risk_threshold}
                      {block.payload.model.detection_run &&
                        ` · ${block.payload.model.detection_run}`}
                    </div>
                  )}
                </button>

                {open && (
                  <pre className="max-h-72 overflow-auto bg-zinc-100 px-4 py-3 text-[10px] leading-relaxed text-zinc-600 dark:bg-zinc-950 dark:text-zinc-400">
                    {JSON.stringify(block.payload, null, 2)}
                  </pre>
                )}
              </div>
            )
          })}
      </div>
    </div>
  )
}
