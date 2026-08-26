import { useEffect, useState } from 'react'
import { getCompany, getDismissalReasons } from '../api'
import { useAuth } from '../useAuth.jsx'
import { Banner, Button, Select, Textarea } from './ui.jsx'
import { HubIcon, LoopIcon, ShieldIcon } from '../icons.jsx'

/**
 * The evidence panel.
 *
 * Shows either a selected alert (its companies, the pattern, why it was
 * flagged, and the two review actions) or a single company drilled into from
 * the graph. The explanation is the part that matters: a risk score nobody can
 * interrogate is not usable evidence, so every reason is rendered as a sentence
 * with its direction, not as a feature name and a number.
 *
 * Both review actions live here, deliberately side by side. Confirming was
 * always possible; dismissing was not, which meant the system could only ever
 * be told it was right. A cleared alert is the only record of where the
 * detector was wrong, and it is the training data that lets it improve.
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
      <p className="text-xs text-zinc-500">
        No explanation yet — run detection to generate one.
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
                raises ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
              }`}
              title={raises ? 'Increases risk' : 'Decreases risk'}
            >
              {raises ? '▲' : '▼'}
            </span>
            <span className="text-zinc-700 dark:text-zinc-300">{reason.text}</span>
          </li>
        )
      })}
    </ul>
  )
}

function Section({ title, children }) {
  return (
    <div className="border-t border-zinc-200 px-4 py-3 dark:border-zinc-800">
      <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-zinc-500">
        {title}
      </h3>
      {children}
    </div>
  )
}

function riskTextColour(score, threshold = 70) {
  if (score >= threshold) return 'text-red-600 dark:text-red-400'
  if (score >= threshold * 0.57) return 'text-amber-600 dark:text-amber-400'
  return 'text-green-600 dark:text-green-400'
}

/** The dismiss flow: pick a reason, add an optional note, confirm. */
function DismissForm({ onCancel, onSubmit, busy }) {
  const [reasons, setReasons] = useState([])
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')

  useEffect(() => {
    getDismissalReasons()
      .then((data) => {
        setReasons(data)
        setReason(data[0]?.code || '')
      })
      .catch(() => setReasons([]))
  }, [])

  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3.5 dark:border-zinc-700 dark:bg-zinc-800/60">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500">
        Why is this not fraud?
      </p>
      <Select value={reason} onChange={(e) => setReason(e.target.value)} className="py-1.5 text-xs">
        {reasons.map((r) => (
          <option key={r.code} value={r.code}>
            {r.label}
          </option>
        ))}
      </Select>
      <Textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={2}
        placeholder="Optional note for the case record…"
        className="mt-2 text-xs"
      />
      <div className="mt-2.5 flex gap-2">
        <Button
          variant="subtle"
          size="sm"
          className="flex-1"
          onClick={() => onSubmit(reason, note)}
          disabled={!reason || busy}
        >
          {busy ? 'Recording…' : 'Clear this alert'}
        </Button>
        <Button size="sm" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
      <p className="mt-2.5 text-[10px] leading-relaxed text-zinc-500">
        Clearing is recorded as training data and written to the audit ledger. It is how the
        detector learns what ordinary trade looks like.
      </p>
    </div>
  )
}

function MillEvidence({ evidence }) {
  const rows = [
    ['Sales invoiced', formatInr(evidence.sales_value)],
    ['Purchases booked', formatInr(evidence.purchase_value)],
    ['Distinct buyers', evidence.buyer_count],
    ['Distinct suppliers', evidence.supplier_count],
    ['Declared turnover', formatInr(evidence.declared_turnover)],
    ['Registered', `${evidence.days_since_registration} days ago`],
  ]
  return (
    <dl className="space-y-1 text-xs">
      {rows.map(([label, value]) => (
        <div key={label} className="flex gap-2">
          <dt className="w-36 shrink-0 text-zinc-500 dark:text-zinc-600">{label}</dt>
          <dd className="text-zinc-700 dark:text-zinc-300">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function RingPanel({ ring, onConfirm, onDismiss, onSelectCompany, reviewing, riskThreshold }) {
  const { can } = useAuth()
  const canConfirm = can.can_confirm
  const [dismissing, setDismissing] = useState(false)
  const isMill = ring.kind === 'mill'
  const decided = ring.status !== 'pending'

  useEffect(() => {
    setDismissing(false)
  }, [ring.id])

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900 dark:text-zinc-200">
            <span className={isMill ? 'text-amber-600 dark:text-amber-400' : 'text-zinc-400'}>
              {isMill ? <HubIcon className="h-4 w-4" /> : <LoopIcon className="h-4 w-4" />}
            </span>
            {isMill ? 'Mill' : 'Ring'} {ring.id}
          </h2>
          <span className={`text-2xl font-semibold ${riskTextColour(ring.risk_score, riskThreshold)}`}>
            {ring.risk_score.toFixed(1)}
          </span>
        </div>
        <p className="text-xs text-zinc-500">
          {isMill
            ? `${ring.ring_size - 1} buyers · ${formatInr(ring.total_cycle_value)} invoiced out`
            : `${ring.ring_size} companies · ${formatInr(ring.total_cycle_value)} circulating`}{' '}
          · {ring.invoices?.length ?? 0} invoices
        </p>

        {isMill && (
          <p className="mt-2 rounded bg-amber-50 px-2 py-1.5 text-[11px] leading-relaxed text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
            This is not a loop. It was found by the mill detector, which looks for
            companies that sell to many buyers and buy from almost nobody — a pattern
            circular-trade detection cannot see at all.
          </p>
        )}

        {ring.closure === 'control' && (
          <p className="mt-2 rounded bg-amber-50 px-2 py-1.5 text-[11px] leading-relaxed text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
            This loop closes through <strong>shared ownership</strong>, not through an
            invoice — two of its companies share a director or a registered address.
            Invoice-only detection would never find it.
          </p>
        )}
      </div>

      <Section title="WHY THIS WAS FLAGGED">
        <ExplanationList reasons={ring.explanation} />
      </Section>

      {isMill && ring.evidence?.buyer_count !== undefined && (
        <Section title="THE NUMBERS">
          <MillEvidence evidence={ring.evidence} />
        </Section>
      )}

      <Section title={isMill ? 'THE COMPANY AND ITS BUYERS' : 'THE LOOP'}>
        <ol className="space-y-1.5">
          {(ring.companies || []).map((company, i) => (
            <li key={company.id} className="flex items-start gap-2 text-xs">
              <span className="mt-0.5 font-mono text-zinc-400 dark:text-zinc-600">
                {isMill
                  ? i === 0
                    ? '★'
                    : '·'
                  : `${i + 1}${i === (ring.companies || []).length - 1 ? '↩' : '↓'}`}
              </span>
              <button
                onClick={() => onSelectCompany(company.id)}
                className="text-left hover:underline"
              >
                <span className="text-zinc-900 dark:text-zinc-200">{company.name}</span>
                <span className="block font-mono text-[10px] text-zinc-500">
                  {company.gstin}
                </span>
                <span className="block text-[10px] text-zinc-400 dark:text-zinc-600">
                  Director: {company.director_name}
                </span>
              </button>
            </li>
          ))}
        </ol>
      </Section>

      <Section title={isMill ? 'INVOICES ISSUED' : 'INVOICES IN THE LOOP'}>
        <div className="max-h-52 overflow-y-auto">
          <table className="w-full text-[11px]">
            <thead className="text-zinc-500 dark:text-zinc-600">
              <tr className="text-left">
                <th className="pb-1 font-normal">Date</th>
                <th className="pb-1 font-normal">Flow</th>
                <th className="pb-1 text-right font-normal">Amount</th>
                <th className="pb-1 text-center font-normal">E-way</th>
              </tr>
            </thead>
            <tbody className="text-zinc-600 dark:text-zinc-400">
              {(ring.invoices || []).map((inv) => (
                <tr key={inv.id} className="border-t border-zinc-200/70 dark:border-zinc-800/50">
                  <td className="whitespace-nowrap py-1">{inv.date}</td>
                  <td className="truncate py-1" title={`${inv.seller_name} → ${inv.buyer_name}`}>
                    {inv.seller_name} → {inv.buyer_name}
                  </td>
                  <td className="whitespace-nowrap py-1 text-right">{formatInr(inv.amount)}</td>
                  <td className="py-1 text-center">
                    {inv.has_eway_bill ? (
                      <span className="text-zinc-400 dark:text-zinc-600">yes</span>
                    ) : (
                      <span className="text-red-600 dark:text-red-400">no</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="mt-auto border-t border-zinc-200 p-4 dark:border-zinc-800">
        {ring.status === 'confirmed' && (
          <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300">
            Confirmed as fraudulent
            {ring.reviewed_by_name ? ` by ${ring.reviewed_by_name}` : ''}. Evidence is
            recorded in the audit ledger and can no longer be silently altered.
            {ring.review_note && (
              <span className="mt-1 block italic opacity-80">“{ring.review_note}”</span>
            )}
          </div>
        )}

        {ring.status === 'dismissed' && (
          <div className="rounded border border-zinc-300 bg-zinc-100 px-3 py-2 text-xs text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
            Cleared as not fraud
            {ring.reviewed_by_name ? ` by ${ring.reviewed_by_name}` : ''}
            {ring.dismissal_reason_label ? ` — ${ring.dismissal_reason_label}` : ''}.
            {ring.review_note && (
              <span className="mt-1 block italic opacity-80">“{ring.review_note}”</span>
            )}
            <span className="mt-1 block text-[10px] opacity-80">
              You can still confirm it later if new evidence appears.
            </span>
          </div>
        )}

        {!decided && !dismissing && (
          <>
            <div className="flex gap-2">
              {canConfirm ? (
                <Button
                  variant="danger"
                  className="flex-1"
                  onClick={() => onConfirm(ring.id)}
                  disabled={reviewing}
                >
                  {reviewing ? 'Recording…' : 'Confirm as fraudulent'}
                </Button>
              ) : (
                <Button
                  variant="danger"
                  className="flex-1"
                  disabled
                  title="Only a supervisor can confirm an alert as fraudulent"
                >
                  Confirm as fraudulent
                </Button>
              )}
              <Button className="flex-1" onClick={() => setDismissing(true)} disabled={reviewing}>
                Not fraud
              </Button>
            </div>

            {!canConfirm && (
              <Banner tone="info" className="mt-2.5">
                <ShieldIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Confirming starts recovery proceedings against a real business, so it is a
                  supervisor's decision. Clear it if it is not fraud, or leave it for review.
                </span>
              </Banner>
            )}

            <p className="mt-2.5 text-[10px] leading-relaxed text-zinc-500">
              Both decisions are written to the tamper-evident ledger and both become training
              data. Nothing here blocks a refund — every enforcement action stays a human
              decision.
            </p>
          </>
        )}

        {ring.status === 'dismissed' && !dismissing && canConfirm && (
          <Button
            size="sm"
            className="mt-2 w-full border-red-300 text-red-700 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950/40"
            onClick={() => onConfirm(ring.id)}
            disabled={reviewing}
          >
            Reopen and confirm as fraudulent
          </Button>
        )}

        {dismissing && (
          <DismissForm
            busy={reviewing}
            onCancel={() => setDismissing(false)}
            onSubmit={(reason, note) => onDismiss(ring.id, reason, note)}
          />
        )}
      </div>
    </div>
  )
}

function SingleCompanyPanel({ companyId, onBack, riskThreshold }) {
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

  if (error) return <p className="p-4 text-xs text-red-600 dark:text-red-400">{error}</p>
  if (!company) return <p className="p-4 text-xs text-zinc-500">Loading company…</p>

  const score = company.risk_score

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="px-4 py-3">
        <button
          onClick={onBack}
          className="mb-2 text-[11px] text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300"
        >
          ← Back to alert
        </button>
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-200">
            {company.name}
          </h2>
          <span className={`text-2xl font-semibold ${riskTextColour(score ?? 0, riskThreshold)}`}>
            {score === null ? '—' : score.toFixed(1)}
          </span>
        </div>
        <p className="font-mono text-[11px] text-zinc-500">{company.gstin}</p>
      </div>

      <Section title="REGISTRATION">
        <dl className="space-y-1 text-xs">
          {[
            ['PAN', company.pan],
            ['Director', company.director_name],
            ['Address', company.registered_address],
            ['Registered', company.registered_date],
            ['Declared turnover', formatInr(company.declared_turnover)],
            [
              'Invoices',
              `${company.total_sales_count} sales · ${company.total_purchase_count} purchases`,
            ],
          ].map(([label, value]) => (
            <div key={label} className="flex gap-2">
              <dt className="w-32 shrink-0 text-zinc-500 dark:text-zinc-600">{label}</dt>
              <dd className="text-zinc-700 dark:text-zinc-300">{value}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section title="WHY THIS SCORE">
        <ExplanationList reasons={company.explanation} />
      </Section>

      {company.rings?.length > 0 && (
        <Section title="APPEARS IN">
          <ul className="space-y-1 text-xs text-zinc-600 dark:text-zinc-400">
            {company.rings.map((r) => (
              <li key={r.id}>
                {r.kind === 'mill' ? 'Mill' : 'Ring'} {r.id} — {r.ring_size} companies, risk{' '}
                {r.risk_score.toFixed(1)}
                {r.status === 'confirmed' && (
                  <span className="ml-1 text-red-600 dark:text-red-400">(confirmed)</span>
                )}
                {r.status === 'dismissed' && (
                  <span className="ml-1 text-zinc-500">(cleared)</span>
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
  onDismiss,
  onSelectCompany,
  onClearCompany,
  reviewing,
  riskThreshold = 70,
}) {
  if (companyId) {
    return (
      <SingleCompanyPanel
        companyId={companyId}
        onBack={onClearCompany}
        riskThreshold={riskThreshold}
      />
    )
  }

  if (!ring) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center">
        <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-600">
          Select an alert from the feed to see its companies, the invoices behind it, and
          why the model flagged it. Then confirm it as fraud or clear it — both decisions
          teach the detector.
        </p>
      </div>
    )
  }

  return (
    <RingPanel
      ring={ring}
      onConfirm={onConfirm}
      onDismiss={onDismiss}
      onSelectCompany={onSelectCompany}
      reviewing={reviewing}
      riskThreshold={riskThreshold}
    />
  )
}
