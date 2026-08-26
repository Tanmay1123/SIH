import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getMailStatus, getReport, getReports, resendReport } from '../api'
import {
  Badge,
  Banner,
  Button,
  Card,
  CardHeader,
  EmptyState,
  formatInr,
  formatWhen,
  Mono,
  PageHeader,
  Spinner,
  Stat,
} from '../components/ui.jsx'
import { ChainIcon, CloseIcon, DocumentIcon, MailIcon } from '../icons.jsx'

/**
 * Case reports issued to supervisors.
 *
 * The output of this system is not a screen - it is a document that lands in
 * somebody's inbox and can later be proven to be the document that was sent.
 * Each report's SHA-256 hash goes into the audit ledger at the moment it is
 * issued, before delivery is even attempted.
 */
export default function ReportsPage() {
  const [reports, setReports] = useState([])
  const [mail, setMail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [preview, setPreview] = useState(null)

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

  const handleResend = async (id) => {
    setBusy(id)
    setError(null)
    try {
      await resendReport(id)
      await load()
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(null)
    }
  }

  const sent = reports.filter((r) => r.status === 'sent').length
  const failed = reports.filter((r) => r.status === 'failed').length

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-6">
        <PageHeader
          title="Case reports"
          subtitle="A one-page summary of a run's confirmed cases, sent to you and your supervisor, and hashed into the audit ledger."
          actions={
            <Link to="/detections">
              <Button variant="primary">Issue a new report</Button>
            </Link>
          }
        />

        <MailStatus mail={mail} />

        {error && (
          <Banner tone="danger" className="mb-4">
            {error}
          </Banner>
        )}

        {reports.length > 0 && (
          <div className="mb-4 grid gap-4 sm:grid-cols-3">
            <Card className="p-5">
              <Stat label="Issued" value={reports.length} />
            </Card>
            <Card className="p-5">
              <Stat label="Delivered" value={sent} tone="good" />
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
              title="No reports issued yet"
              action={
                <Link to="/detections">
                  <Button variant="primary" size="sm">
                    Go to Detections
                  </Button>
                </Link>
              }
            >
              Work through a run's alerts, then issue a report. It goes to you and every
              configured supervisor, and its content hash is written to the ledger so the
              document can always be proven authentic.
            </EmptyState>
          </Card>
        )}

        <div className="space-y-3">
          {reports.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              busy={busy === report.id}
              onResend={handleResend}
              onPreview={async (id) => {
                try {
                  setPreview(await getReport(id))
                } catch (e) {
                  setError(e.message)
                }
              }}
            />
          ))}
        </div>
      </div>

      {preview && <PreviewOverlay report={preview} onClose={() => setPreview(null)} />}
    </div>
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
            SMTP is not configured, so reports are written to the backend console instead of
            being emailed. Set <Mono>EMAIL_HOST</Mono> in <Mono>.env</Mono> to send them for
            real. Everything else about the workflow works exactly the same.
          </>
        )}
      </span>
    </Banner>
  )
}

function ReportCard({ report, busy, onResend, onPreview }) {
  const failed = report.status === 'failed'
  const tone = report.status === 'sent' ? 'good' : failed ? 'danger' : 'neutral'

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {report.title}
            </h3>
            <Badge tone={tone}>{report.status_label}</Badge>
          </div>
          <p className="mt-1 text-[11px] text-zinc-500">
            {report.dataset_name} · {formatWhen(report.generated_at)}
            {report.generated_by_name && ` · ${report.generated_by_name}`}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button size="sm" variant="outline" onClick={() => onPreview(report.id)}>
            Preview
          </Button>
          <Button size="sm" variant="outline" onClick={() => onResend(report.id)} disabled={busy}>
            {busy ? <Spinner /> : null}
            {failed ? 'Retry send' : 'Send again'}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 px-5 py-4 sm:grid-cols-4">
        <Stat label="Confirmed" value={report.summary?.confirmed_count ?? 0} tone="danger" />
        <Stat label="Value at risk" value={formatInr(report.summary?.confirmed_value)} />
        <Stat label="Companies" value={report.summary?.companies_implicated ?? 0} />
        <Stat label="Cleared" value={report.summary?.dismissed_count ?? 0} tone="good" />
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
        <Mono className="truncate">to {(report.recipients || []).join(', ') || 'nobody'}</Mono>
      </div>
    </Card>
  )
}

function PreviewOverlay({ report, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/70 p-6 backdrop-blur-sm">
      <div className="flex max-h-full w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex items-center justify-between gap-4 border-b border-zinc-200 px-5 py-3.5 dark:border-zinc-800">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {report.title}
            </h3>
            <Mono className="truncate">sha256 {report.content_hash}</Mono>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto bg-zinc-100 dark:bg-zinc-950">
          {/* Rendered exactly as the supervisor receives it, sandboxed so its
              inline email styles cannot leak into the console. */}
          <iframe
            title={report.title}
            srcDoc={report.html}
            sandbox=""
            className="h-[72vh] w-full border-0 bg-white"
          />
        </div>
      </div>
    </div>
  )
}
