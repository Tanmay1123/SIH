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
            The ledger is empty. Confirm a ring as fraudulent and its evidence
            will be recorded here permanently.
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
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-zinc-900 dark:text-zinc-200">
                      Block #{block.index}
                    </span>
                    <span className="text-[11px] text-zinc-500">
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
                  <div className="mt-1 text-[11px] text-zinc-600 dark:text-zinc-400">
                    Ring {block.payload?.ring_id} · {block.payload?.ring_size} companies ·
                    risk {block.payload?.risk_score} · confirmed by{' '}
                    {block.payload?.confirmed_by}
                  </div>
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
