import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  createCompanyReport,
  createReport,
  downloadReportPdf,
  getMailStatus,
  getReportPdfBlob,
  getReports,
  getRuns,
  resendReport,
  searchCompanies,
} from '../api'
import {
  Badge,
  Banner,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  Dialog,
  EmptyState,
  Field,
  Input,
  Select,
  formatInr,
  formatWhen,
  Mono,
  PageHeader,
  Spinner,
  Stat,
} from '../components/ui.jsx'
import { ChainIcon, DocumentIcon, MailIcon, SearchIcon } from '../icons.jsx'

const TYPE_TABS = [
  { key: 'all', label: 'All' },
  { key: 'run', label: 'Run' },
  { key: 'company', label: 'Company' },
]

const STATUS_TABS = [
  { key: 'all', label: 'All' },
  { key: 'draft', label: 'Not sent' },
  { key: 'sent', label: 'Sent' },
  { key: 'failed', label: 'Failed' },
]

/**
 * Reports: a run's case report, or one flagged company's own report.
 *
 * The output of this system is not a screen - it is a document. Each one is
 * rendered once as HTML, hashed into the audit ledger the moment it is
 * issued, and turned into a PDF on request - the same PDF whether it is
 * viewed here, downloaded, or attached to the email a supervisor receives.
 *
 * Generating a report and sending it are two separate actions. A report is
 * hashed into the ledger as soon as it exists, so what was issued is on
 * record either way - but nothing reaches an inbox until "Send" is pressed
 * and confirmed. That confirmation is not decoration: unlike almost
 * everything else in this console, sending an email cannot be undone by
 * fixing a row in a database afterwards.
 */
export default function ReportsPage() {
  const [reports, setReports] = useState([])
  const [mail, setMail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [viewing, setViewing] = useState(null) // { report, url }
  const [sending, setSending] = useState(null) // report being confirmed
  const [showGenerate, setShowGenerate] = useState(false)
  const [filterType, setFilterType] = useState('all')
  const [filterStatus, setFilterStatus] = useState('all')
  const [query, setQuery] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [reportData, mailData] = await Promise.all([getReports(), getMailStatus()])
      setReports(reportData)
      setMail(mailData)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // The blob URL a PDF viewer is pointed at is only valid for this tab's
  // lifetime and must be revoked when done with it, or the file stays pinned
  // in memory for as long as the page is open.
  useEffect(() => {
    return () => {
      if (viewing?.url) URL.revokeObjectURL(viewing.url)
    }
  }, [viewing])

  const handleView = async (report) => {
    setBusy(`view-${report.id}`)
    setError(null)
    try {
      const blob = await getReportPdfBlob(report.id)
      setViewing({ report, url: URL.createObjectURL(blob) })
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(null)
    }
  }

  const handleDownload = async (report) => {
    setBusy(`dl-${report.id}`)
    setError(null)
    try {
      await downloadReportPdf(report.id)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(null)
    }
  }

  const handleConfirmSend = async () => {
    const report = sending
    setBusy(`send-${report.id}`)
    setError(null)
    try {
      await resendReport(report.id)
      setSending(null)
      await load()
      setNotice(`Sent to ${(report.recipients || []).join(', ') || 'nobody — no recipients configured'}.`)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(null)
    }
  }

  const handleGenerated = async (report) => {
    setShowGenerate(false)
    await load()
    setNotice(`"${report.title}" generated. Find it at the top of the list below.`)
  }

  const sent = reports.filter((r) => r.status === 'sent').length
  const failed = reports.filter((r) => r.status === 'failed').length

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return reports.filter((r) => {
      if (filterType !== 'all' && r.report_type !== filterType) return false
      if (filterStatus !== 'all' && r.status !== filterStatus) return false
      if (!q) return true
      return [r.title, r.dataset_name, r.company_name, r.company_gstin]
        .filter(Boolean)
        .some((field) => field.toLowerCase().includes(q))
    })
  }, [reports, filterType, filterStatus, query])

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-6">
        <PageHeader
          title="Reports"
          subtitle="A run's case report, or one flagged company's own report. Every one is hashed into the audit ledger the moment it is generated."
          actions={
            <Button variant="primary" onClick={() => setShowGenerate(true)}>
              <DocumentIcon className="h-4 w-4" />
              Generate a report
            </Button>
          }
        />

        <MailStatus mail={mail} />

        {error && (
          <Banner tone="danger" className="mb-4">
            {error}
          </Banner>
        )}
        {notice && (
          <Banner tone="good" className="mb-4">
            <MailIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {notice}
          </Banner>
        )}

        {reports.length > 0 && (
          <div className="mb-4 grid gap-4 sm:grid-cols-3">
            <Card className="p-5">
              <Stat label="Generated" value={reports.length} />
            </Card>
            <Card className="p-5">
              <Stat label="Sent" value={sent} tone="good" />
            </Card>
            <Card className="p-5">
              <Stat
                label="Failed"
                value={failed}
                tone={failed ? 'danger' : 'muted'}
                hint={failed ? 'fix SMTP and retry' : 'none'}
              />
            </Card>
          </div>
        )}

        {loading && <Card className="p-6 text-sm text-zinc-500">Loading reports…</Card>}

        {!loading && reports.length === 0 && (
          <Card>
            <EmptyState
              icon={<DocumentIcon className="h-5 w-5" />}
              title="No reports generated yet"
              action={
                <Button variant="primary" size="sm" onClick={() => setShowGenerate(true)}>
                  Generate one now
                </Button>
              }
            >
              Generate a run's case report or one flagged company's report right from this
              page. Either way, it is hashed into the ledger immediately and sent only when
              you choose to send it.
            </EmptyState>
          </Card>
        )}

        {!loading && reports.length > 0 && (
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <div className="flex rounded-lg border border-zinc-200 p-0.5 dark:border-zinc-800">
              {TYPE_TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setFilterType(t.key)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    filterType === t.key
                      ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                      : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="flex rounded-lg border border-zinc-200 p-0.5 dark:border-zinc-800">
              {STATUS_TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setFilterStatus(t.key)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    filterStatus === t.key
                      ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                      : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="relative ml-auto w-56">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search title, company, GSTIN…"
                className="h-8 pl-8 text-xs"
              />
            </div>
          </div>
        )}

        {!loading && reports.length > 0 && filtered.length === 0 && (
          <Card className="p-6 text-center text-sm text-zinc-500">
            Nothing matches these filters.
          </Card>
        )}

        <div className="space-y-3">
          {filtered.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              busy={busy}
              onView={handleView}
              onDownload={handleDownload}
              onSend={setSending}
            />
          ))}
        </div>
      </div>

      {viewing && (
        <Dialog
          title={viewing.report.title}
          subtitle={`sha256 ${viewing.report.content_hash}`}
          onClose={() => setViewing(null)}
          size="full"
          footer={
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => handleDownload(viewing.report)}>
                Download
              </Button>
              <Button variant="primary" onClick={() => setViewing(null)}>
                Done
              </Button>
            </div>
          }
        >
          <iframe
            title={viewing.report.title}
            src={viewing.url}
            className="h-[85vh] w-full border-0"
          />
        </Dialog>
      )}

      {sending && (
        <ConfirmDialog
          title="Send this report?"
          confirmLabel="Send"
          busy={busy === `send-${sending.id}`}
          onConfirm={handleConfirmSend}
          onClose={() => setSending(null)}
        >
          <p>
            <strong className="text-zinc-900 dark:text-zinc-100">{sending.title}</strong> will be
            emailed as a PDF attachment to:
          </p>
          <ul className="mt-2 space-y-1">
            {(sending.recipients || []).length > 0 ? (
              sending.recipients.map((email) => (
                <li key={email} className="font-mono text-xs">
                  {email}
                </li>
              ))
            ) : (
              <li className="text-amber-600 dark:text-amber-400">
                Nobody — no recipients are configured. Add an email on your{' '}
                <Link to="/profile" className="underline">
                  profile
                </Link>{' '}
                first.
              </li>
            )}
          </ul>
          <p className="mt-3 text-xs text-zinc-500">This cannot be undone once it sends.</p>
        </ConfirmDialog>
      )}

      {showGenerate && (
        <GenerateDialog onClose={() => setShowGenerate(false)} onGenerated={handleGenerated} />
      )}
    </div>
  )
}

/**
 * Generate either report shape without leaving this page: pick a detection
 * run, or find a company by name/GSTIN. Both call through to the same
 * create-and-hash-into-the-ledger endpoints the Detections page and the
 * company drill-down panel use - this is a second door into the same room,
 * not a separate code path to keep in sync.
 */
function GenerateDialog({ onClose, onGenerated }) {
  const [tab, setTab] = useState('run')
  const [runs, setRuns] = useState([])
  const [runsLoading, setRunsLoading] = useState(true)
  const [runId, setRunId] = useState('')
  const [companyQuery, setCompanyQuery] = useState('')
  const [companyResults, setCompanyResults] = useState([])
  const [company, setCompany] = useState(null)
  const [searching, setSearching] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    getRuns()
      .then((data) => {
        setRuns(data)
        if (data.length) setRunId(String(data[0].id))
      })
      .catch((e) => setError(e?.response?.data?.detail || e.message))
      .finally(() => setRunsLoading(false))
  }, [])

  useEffect(() => {
    if (tab !== 'company' || company || !companyQuery.trim()) {
      setCompanyResults([])
      return undefined
    }
    setSearching(true)
    const timer = setTimeout(() => {
      searchCompanies(companyQuery.trim())
        .then(setCompanyResults)
        .catch(() => setCompanyResults([]))
        .finally(() => setSearching(false))
    }, 250)
    return () => clearTimeout(timer)
  }, [tab, companyQuery, company])

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const report =
        tab === 'run'
          ? await createReport(runId, { title: `Case report — ${runs.find((r) => String(r.id) === runId)?.name || ''}` })
          : await createCompanyReport(company.id)
      onGenerated(report)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  const canSubmit = tab === 'run' ? Boolean(runId) : Boolean(company)

  return (
    <Dialog
      title="Generate a report"
      subtitle="A run's full case report, or one company's own report — either way it's hashed into the ledger immediately."
      onClose={busy ? undefined : onClose}
      footer={
        <div className="flex gap-2">
          <Button
            variant="primary"
            className="flex-1"
            onClick={submit}
            disabled={!canSubmit || busy}
          >
            {busy ? <Spinner className="h-3.5 w-3.5" /> : null}
            {busy ? 'Generating…' : 'Generate'}
          </Button>
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
        </div>
      }
    >
      <div className="mb-4 flex rounded-lg border border-zinc-200 p-0.5 dark:border-zinc-800">
        <button
          onClick={() => setTab('run')}
          className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            tab === 'run'
              ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
              : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
          }`}
        >
          From a detection run
        </button>
        <button
          onClick={() => setTab('company')}
          className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            tab === 'company'
              ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
              : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
          }`}
        >
          For one company
        </button>
      </div>

      {error && (
        <Banner tone="danger" className="mb-3">
          {error}
        </Banner>
      )}

      {tab === 'run' ? (
        <Field label="Detection run" hint="The full case report: every alert, confirmed and cleared, in this run.">
          {runsLoading ? (
            <p className="text-xs text-zinc-500">Loading runs…</p>
          ) : runs.length === 0 ? (
            <p className="text-xs text-zinc-500">
              No detection runs yet.{' '}
              <Link to="/detections" className="underline">
                Run detection first.
              </Link>
            </p>
          ) : (
            <Select value={runId} onChange={(e) => setRunId(e.target.value)}>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} — {r.dataset_name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      ) : (
        <Field
          label="Find a company"
          hint="By name or GSTIN. Its report covers registration details and why its score is what it is."
        >
          {company ? (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 dark:border-brand-800 dark:bg-brand-900/20">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {company.name}
                </p>
                <p className="font-mono text-[11px] text-zinc-500">{company.gstin}</p>
              </div>
              <button
                onClick={() => {
                  setCompany(null)
                  setCompanyQuery('')
                }}
                className="shrink-0 text-xs font-medium text-brand-700 underline dark:text-brand-300"
              >
                Change
              </button>
            </div>
          ) : (
            <>
              <div className="relative">
                <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
                <Input
                  autoFocus
                  value={companyQuery}
                  onChange={(e) => setCompanyQuery(e.target.value)}
                  placeholder="e.g. Sharma Textiles or 27ABCDE..."
                  className="pl-8"
                />
              </div>
              {searching && <p className="mt-1.5 text-[11px] text-zinc-500">Searching…</p>}
              {companyResults.length > 0 && (
                <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
                  {companyResults.map((c) => (
                    <button
                      key={c.id}
                      onClick={() => setCompany(c)}
                      className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    >
                      <span className="truncate text-sm text-zinc-800 dark:text-zinc-200">
                        {c.name}
                      </span>
                      <span className="shrink-0 font-mono text-[11px] text-zinc-500">
                        {c.gstin}
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {!searching && companyQuery.trim() && companyResults.length === 0 && (
                <p className="mt-1.5 text-[11px] text-zinc-500">No match in the active dataset.</p>
              )}
            </>
          )}
        </Field>
      )}
    </Dialog>
  )
}

function MailStatus({ mail }) {
  if (!mail) return null

  if (mail.configured && mail.recipients?.length) {
    return (
      <Banner tone="good" className="mb-4">
        <MailIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          Reports go to <strong>{mail.recipients.join(', ')}</strong>.
        </span>
      </Banner>
    )
  }

  return (
    <Banner tone="warn" className="mb-4">
      <MailIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>
        {!mail.recipients?.length ? (
          <>
            No recipients yet. Add an email to your account on the{' '}
            <Link to="/profile" className="underline">
              profile page
            </Link>
            , or set supervisor addresses in{' '}
            <Link to="/settings" className="underline">
              settings
            </Link>
            .
          </>
        ) : (
          <>
            SMTP is not configured, so sending will fail until it is. Set{' '}
            <Mono>EMAIL_HOST</Mono> in <Mono>.env</Mono> to send for real — everything else
            about the workflow, including viewing and downloading the PDF, works already.
          </>
        )}
      </span>
    </Banner>
  )
}

function ReportCard({ report, busy, onView, onDownload, onSend }) {
  const failed = report.status === 'failed'
  const tone = report.status === 'sent' ? 'good' : failed ? 'danger' : 'neutral'
  const isCompany = report.report_type === 'company'

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {report.title}
            </h3>
            <Badge tone={isCompany ? 'info' : 'neutral'}>
              {isCompany ? 'Company' : 'Run'}
            </Badge>
            <Badge tone={tone}>{report.status_label}</Badge>
          </div>
          <p className="mt-1 text-[11px] text-zinc-500">
            {isCompany ? (
              <>
                {report.company_name} <Mono className="text-[10px]">{report.company_gstin}</Mono>
              </>
            ) : (
              report.dataset_name
            )}{' '}
            · {formatWhen(report.generated_at)}
            {report.generated_by_name && ` · ${report.generated_by_name}`}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => onView(report)}
            disabled={busy === `view-${report.id}`}
          >
            {busy === `view-${report.id}` ? <Spinner /> : null}
            View PDF
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onDownload(report)}
            disabled={busy === `dl-${report.id}`}
          >
            {busy === `dl-${report.id}` ? <Spinner /> : null}
            Download
          </Button>
          <Button size="sm" variant="primary" onClick={() => onSend(report)}>
            {failed ? 'Retry send' : report.status === 'sent' ? 'Send again' : 'Send'}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 px-5 py-4 sm:grid-cols-4">
        {isCompany ? (
          <>
            <Stat
              label="Risk score"
              value={report.summary?.risk_score ?? '—'}
              tone={report.summary?.risk_score >= 70 ? 'danger' : 'default'}
            />
            <Stat label="Sales invoices" value={report.summary?.sales_count ?? 0} />
            <Stat label="Purchase invoices" value={report.summary?.purchase_count ?? 0} />
            <Stat label="Appears in" value={report.summary?.alerts?.length ?? 0} tone="warn" />
          </>
        ) : (
          <>
            <Stat label="Confirmed" value={report.summary?.confirmed_count ?? 0} tone="danger" />
            <Stat label="Value at risk" value={formatInr(report.summary?.confirmed_value)} />
            <Stat label="Companies" value={report.summary?.companies_implicated ?? 0} />
            <Stat label="Cleared" value={report.summary?.dismissed_count ?? 0} tone="good" />
          </>
        )}
      </div>

      {failed && report.error && (
        <div className="px-5 pb-3">
          <Banner tone="danger">{report.error}</Banner>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-zinc-200 px-5 py-2.5 dark:border-zinc-800">
        <Mono className="flex items-center gap-1.5">
          <ChainIcon className="h-3 w-3" />
          sha256 {report.content_hash?.slice(0, 20)}…
        </Mono>
        {report.ledger_index !== null && <Mono>ledger block #{report.ledger_index}</Mono>}
        <Mono className="truncate">to {(report.recipients || []).join(', ') || 'nobody yet'}</Mono>
      </div>
    </Card>
  )
}
