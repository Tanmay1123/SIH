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
      <div className="border-b border-slate-800 px-4 py-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold tracking-wide text-slate-200">
            AUDIT LEDGER
          </h2>
          {chain && (
            <span
              className={`rounded border px-2 py-0.5 text-[11px] font-medium ${
                chain.valid
                  ? 'border-emerald-800 bg-emerald-950 text-emerald-300'
                  : 'border-red-800 bg-red-950 text-red-300'
              }`}
            >
              {chain.valid ? 'CHAIN INTACT' : 'CHAIN BROKEN'}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {chain?.message || 'Checking chain…'}
        </p>
        <p className="mt-1 text-[10px] leading-relaxed text-slate-600">
          A local SHA-256 hash chain — not a cryptocurrency. No wallet, no token,
          no gas fee, no public network. Each block hashes its own contents plus
          the previous block's hash, so editing any past record breaks every
          block after it.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && <p className="px-4 py-6 text-sm text-slate-500">Loading ledger…</p>}

        {!loading && blocks.length === 0 && (
          <p className="px-4 py-6 text-sm text-slate-500">
            The ledger is empty. Confirm a ring as fraudulent and its evidence
            will be recorded here permanently.
          </p>
        )}

        {!loading &&
          blocks.map((block) => {
            const open = expanded === block.index
            return (
              <div key={block.index} className="border-b border-slate-800/70">
                <button
                  onClick={() => setExpanded(open ? null : block.index)}
                  className="w-full px-4 py-3 text-left hover:bg-slate-800/40"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-slate-200">
                      Block #{block.index}
                    </span>
                    <span className="text-[11px] text-slate-500">
                      {new Date(block.timestamp).toLocaleString('en-IN')}
                    </span>
                  </div>
                  <div className="mt-1 space-y-0.5 font-mono text-[10px]">
                    <div className="flex gap-2 text-slate-500">
                      <span className="w-14 shrink-0">hash</span>
                      <span className="text-cyan-400">{short(block.hash)}</span>
                    </div>
                    <div className="flex gap-2 text-slate-500">
                      <span className="w-14 shrink-0">links to</span>
                      <span className="text-slate-400">{short(block.previous_hash)}</span>
                      {block.index === 0 && (
                        <span className="text-slate-600">(genesis)</span>
                      )}
                    </div>
                  </div>
                  <div className="mt-1 text-[11px] text-slate-400">
                    Ring {block.payload?.ring_id} · {block.payload?.ring_size} companies ·
                    risk {block.payload?.risk_score} · confirmed by{' '}
                    {block.payload?.confirmed_by}
                  </div>
                </button>

                {open && (
                  <pre className="max-h-72 overflow-auto bg-slate-950 px-4 py-3 text-[10px] leading-relaxed text-slate-400">
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
