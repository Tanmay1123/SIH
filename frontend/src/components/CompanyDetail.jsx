import { useEffect, useState } from 'react'
import { getCompany } from '../api'

/**
 * The evidence panel.
 *
 * Shows either a selected ring (its member companies, the loop, why it was
 * flagged, and the confirm action) or a single company drilled into from the
 * graph. The explanation is the part that matters: a risk score nobody can
 * interrogate is not usable evidence, so every reason is rendered as a
 * sentence with its direction, not as a feature name and a number.
 */

const formatInr = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`
  return `₹${n.toLocaleString('en-IN')}`
}

function ExplanationList({ reasons }) {
  if (!reasons?.length) {
    return (
      <p className="text-xs text-slate-500">
        No explanation yet — run scoring to generate one.
      </p>
    )
  }
  return (
    <ul className="space-y-2">
      {reasons.map((reason, i) => {
        const raises = reason.direction === 'increases_risk'
        return (
          <li key={i} className="flex gap-2 text-xs leading-relaxed">
            <span
              className={`mt-0.5 shrink-0 font-mono text-sm ${
                raises ? 'text-red-400' : 'text-emerald-400'
              }`}
              title={raises ? 'Increases risk' : 'Decreases risk'}
            >
              {raises ? '▲' : '▼'}
            </span>
            <span className="text-slate-300">{reason.text}</span>
          </li>
        )
      })}
    </ul>
  )
}

function Section({ title, children }) {
  return (
    <div className="border-t border-slate-800 px-4 py-3">
      <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-slate-500">
        {title}
      </h3>
      {children}
    </div>
  )
}

function RingPanel({ ring, onConfirm, onSelectCompany, confirming }) {
  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="px-4 py-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-slate-200">Ring {ring.id}</h2>
          <span
            className={`text-2xl font-semibold ${
              ring.risk_score >= 70
                ? 'text-red-400'
                : ring.risk_score >= 40
                  ? 'text-orange-400'
                  : 'text-cyan-400'
            }`}
          >
            {ring.risk_score.toFixed(1)}
          </span>
        </div>
        <p className="text-xs text-slate-500">
          {ring.ring_size} companies · {formatInr(ring.total_cycle_value)} circulating ·{' '}
          {ring.invoices?.length ?? 0} invoices
        </p>
      </div>

      <Section title="WHY THIS WAS FLAGGED">
        <ExplanationList reasons={ring.explanation} />
      </Section>

      <Section title="THE LOOP">
        <ol className="space-y-1.5">
          {(ring.companies || []).map((company, i) => (
            <li key={company.id} className="flex items-start gap-2 text-xs">
              <span className="mt-0.5 font-mono text-slate-600">
                {i + 1}
                {i === (ring.companies || []).length - 1 ? '↩' : '↓'}
              </span>
              <button
                onClick={() => onSelectCompany(company.id)}
                className="text-left hover:underline"
              >
                <span className="text-slate-200">{company.name}</span>
                <span className="block font-mono text-[10px] text-slate-500">
                  {company.gstin}
                </span>
                <span className="block text-[10px] text-slate-600">
                  Director: {company.director_name}
                </span>
              </button>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="INVOICES IN THE LOOP">
        <div className="max-h-52 overflow-y-auto">
          <table className="w-full text-[11px]">
            <thead className="text-slate-600">
              <tr className="text-left">
                <th className="pb-1 font-normal">Date</th>
                <th className="pb-1 font-normal">Flow</th>
                <th className="pb-1 text-right font-normal">Amount</th>
                <th className="pb-1 text-center font-normal">E-way</th>
              </tr>
            </thead>
            <tbody className="text-slate-400">
              {(ring.invoices || []).map((inv) => (
                <tr key={inv.id} className="border-t border-slate-800/50">
                  <td className="py-1 whitespace-nowrap">{inv.date}</td>
                  <td className="py-1 truncate" title={`${inv.seller_name} → ${inv.buyer_name}`}>
                    {inv.seller_name} → {inv.buyer_name}
                  </td>
                  <td className="py-1 text-right whitespace-nowrap">
                    {formatInr(inv.amount)}
                  </td>
                  <td className="py-1 text-center">
                    {inv.has_eway_bill ? (
                      <span className="text-slate-600">yes</span>
                    ) : (
                      <span className="text-red-400">no</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="mt-auto border-t border-slate-800 p-4">
        {ring.officer_confirmed ? (
          <div className="rounded border border-emerald-900 bg-emerald-950/50 px-3 py-2 text-xs text-emerald-300">
            Confirmed as fraudulent. Evidence is recorded in the audit ledger and
            can no longer be silently altered.
          </div>
        ) : (
          <button
            onClick={() => onConfirm(ring.id)}
            disabled={confirming}
            className="w-full rounded bg-red-700 px-3 py-2 text-sm font-medium text-white hover:bg-red-600 disabled:opacity-50"
          >
            {confirming ? 'Recording…' : 'Confirm as fraudulent'}
          </button>
        )}
        <p className="mt-2 text-[10px] leading-relaxed text-slate-600">
          Confirming writes the full evidence bundle to the tamper-evident ledger.
          This action is append-only and cannot be undone.
        </p>
      </div>
    </div>
  )
}

function SingleCompanyPanel({ companyId, onBack }) {
  const [company, setCompany] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setCompany(null)
    setError(null)
    getCompany(companyId)
      .then((data) => !cancelled && setCompany(data))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [companyId])

  if (error) return <p className="p-4 text-xs text-red-400">{error}</p>
  if (!company) return <p className="p-4 text-xs text-slate-500">Loading company…</p>

  const score = company.risk_score

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="px-4 py-3">
        <button
          onClick={onBack}
          className="mb-2 text-[11px] text-slate-500 hover:text-slate-300"
        >
          ← Back to ring
        </button>
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-200">{company.name}</h2>
          <span
            className={`text-2xl font-semibold ${
              score >= 70 ? 'text-red-400' : score >= 40 ? 'text-orange-400' : 'text-cyan-400'
            }`}
          >
            {score === null ? '—' : score.toFixed(1)}
          </span>
        </div>
        <p className="font-mono text-[11px] text-slate-500">{company.gstin}</p>
      </div>

      <Section title="REGISTRATION">
        <dl className="space-y-1 text-xs">
          {[
            ['PAN', company.pan],
            ['Director', company.director_name],
            ['Address', company.registered_address],
            ['Registered', company.registered_date],
            ['Declared turnover', formatInr(company.declared_turnover)],
            ['Invoices', `${company.total_sales_count} sales · ${company.total_purchase_count} purchases`],
          ].map(([label, value]) => (
            <div key={label} className="flex gap-2">
              <dt className="w-32 shrink-0 text-slate-600">{label}</dt>
              <dd className="text-slate-300">{value}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section title="WHY THIS SCORE">
        <ExplanationList reasons={company.explanation} />
      </Section>

      {company.rings?.length > 0 && (
        <Section title="RING MEMBERSHIP">
          <ul className="space-y-1 text-xs text-slate-400">
            {company.rings.map((r) => (
              <li key={r.id}>
                Ring {r.id} — {r.ring_size} companies, risk {r.risk_score.toFixed(1)}
                {r.officer_confirmed && (
                  <span className="ml-1 text-emerald-400">(confirmed)</span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  )
}

export default function CompanyDetail({
  ring,
  companyId,
  onConfirm,
  onSelectCompany,
  onClearCompany,
  confirming,
}) {
  if (companyId) {
    return <SingleCompanyPanel companyId={companyId} onBack={onClearCompany} />
  }

  if (!ring) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center">
        <p className="text-xs leading-relaxed text-slate-600">
          Select a ring from the alerts feed to see its companies, the invoices
          that close the loop, and why the model flagged it.
        </p>
      </div>
    )
  }

  return (
    <RingPanel
      ring={ring}
      onConfirm={onConfirm}
      onSelectCompany={onSelectCompany}
      confirming={confirming}
    />
  )
}
