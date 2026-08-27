import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  createReport,
  deleteRun,
  getRuns,
  runDetection,
  uploadDataset,
} from '../api'
import { useAuth } from '../useAuth.jsx'
import {
  Badge,
  Banner,
  Button,
  Card,
  CardHeader,
  Dialog,
  EmptyState,
  Field,
  formatInr,
  formatWhen,
  Input,
  Mono,
  PageHeader,
  Progress,
  Spinner,
  Stat,
} from '../components/ui.jsx'
import {
  CheckIcon,
  FileIcon,
  PlayIcon,
  PulseIcon,
  TrashIcon,
  UploadIcon,
} from '../icons.jsx'

/**
 * Detection runs, past and present.
 *
 * Every run is kept: a named, dated record of what the detectors found, which
 * model version found it and at what threshold. Nothing overwrites anything,
 * so two runs over the same data can be compared directly - which is the only
 * way to tell whether a change actually improved anything.
 */
export default function DetectionsPage({ status, onChanged }) {
  const { can } = useAuth()
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [showUpload, setShowUpload] = useState(false)
  const [showRun, setShowRun] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRuns(await getRuns())
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const currentRunId = status?.run?.id

  const handleRun = async (name) => {
    setShowRun(false)
    setBusy('run')
    setError(null)
    try {
      await runDetection(name)
      await Promise.all([load(), onChanged()])
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(null)
    }
  }

  const handleDelete = async (run) => {
    if (!window.confirm(`Delete "${run.name}" and every alert it produced?`)) return
    setBusy(`del-${run.id}`)
    setError(null)
    try {
      await deleteRun(run.id)
      await Promise.all([load(), onChanged()])
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(null)
    }
  }

  const [notice, setNotice] = useState(null)

  const handleIssue = async (run) => {
    setBusy(`rep-${run.id}`)
    setError(null)
    setNotice(null)
    try {
      await createReport(run.id, { title: `Case report — ${run.name}` })
      await load()
      // Generating no longer sends it - that is now a deliberate second step
      // on the Reports page, gated behind a confirmation, so the person who
      // clicked "Generate" gets pointed at where to view or send it rather
      // than assuming mail already went out.
      setNotice(
        <>
          Report generated. <Link to="/reports" className="font-medium underline">Open Reports</Link> to
          view the PDF, download it, or send it to your supervisor.
        </>,
      )
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-6">
        <PageHeader
          title="Detection runs"
          subtitle="Each run is a permanent record of what was found, when, and by which model version. Running again never erases the last one."
          actions={
            <>
              {can.can_upload && (
                <Button variant="outline" onClick={() => setShowUpload(true)}>
                  <UploadIcon className="h-4 w-4" />
                  Upload dataset
                </Button>
              )}
              {can.can_run_detection && (
                <Button
                  variant="primary"
                  onClick={() => setShowRun(true)}
                  disabled={busy === 'run' || !(status?.companies > 0)}
                  title={status?.companies > 0 ? undefined : 'Upload a dataset first'}
                >
                  {busy === 'run' ? <Spinner /> : <PlayIcon className="h-4 w-4" />}
                  {busy === 'run' ? 'Running…' : 'Run detection'}
                </Button>
              )}
            </>
          }
        />

        {error && (
          <Banner tone="danger" className="mb-4">
            {error}
          </Banner>
        )}
        {notice && (
          <Banner tone="good" className="mb-4">
            {notice}
          </Banner>
        )}

        {loading && <Card className="p-6 text-sm text-zinc-500">Loading runs…</Card>}

        {!loading && runs.length === 0 && (
          <Card>
            <EmptyState
              icon={<PulseIcon className="h-5 w-5" />}
              title="No detection runs yet"
              action={
                status?.companies > 0 && can.can_run_detection ? (
                  <Button variant="primary" size="sm" onClick={() => setShowRun(true)}>
                    Run the first detection
                  </Button>
                ) : (
                  <Button variant="primary" size="sm" onClick={() => setShowUpload(true)}>
                    Upload a dataset
                  </Button>
                )
              }
            >
              A run searches the active dataset for circular-trade rings and fake invoice
              mills, scores what it finds, and records the model version behind every score.
            </EmptyState>
          </Card>
        )}

        <div className="space-y-3">
          {runs.map((run) => (
            <RunCard
              key={run.id}
              run={run}
              isCurrent={run.id === currentRunId}
              busy={busy}
              canIssue={can.can_issue_report}
              onIssue={handleIssue}
              onDelete={handleDelete}
            />
          ))}
        </div>
      </div>

      {showRun && <RunDialog onClose={() => setShowRun(false)} onRun={handleRun} />}
      {showUpload && (
        <UploadDialog
          onClose={() => setShowUpload(false)}
          onUploaded={async () => {
            setShowUpload(false)
            await Promise.all([load(), onChanged()])
          }}
        />
      )}
    </div>
  )
}

function RunCard({ run, isCurrent, busy, canIssue, onIssue, onDelete }) {
  const total = run.alert_count
  const reviewed = run.reviewed_count
  const complete = total > 0 && reviewed === total

  return (
    <Card className={isCurrent ? 'ring-1 ring-brand-500/40' : undefined}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {run.name}
            </h3>
            {isCurrent && <Badge tone="good">Showing now</Badge>}
            {complete && (
              <Badge tone="good">
                <CheckIcon className="h-2.5 w-2.5" /> Fully reviewed
              </Badge>
            )}
          </div>
          <p className="mt-1 text-[11px] text-zinc-500">
            {run.dataset_name} · {formatWhen(run.started_at)}
            {run.created_by_name && ` · ${run.created_by_name}`}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Link to="/network">
            <Button size="sm" variant="outline">
              Review
            </Button>
          </Link>
          {canIssue && (
            <Button
              size="sm"
              variant="primary"
              onClick={() => onIssue(run)}
              disabled={busy === `rep-${run.id}`}
            >
              {busy === `rep-${run.id}` ? <Spinner /> : null}
              {run.report_count > 0 ? 'Generate again' : 'Generate report'}
            </Button>
          )}
          <button
            onClick={() => onDelete(run)}
            disabled={busy === `del-${run.id}`}
            title="Delete this run"
            className="rounded-lg p-2 text-zinc-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-40 dark:hover:bg-red-950/40 dark:hover:text-red-400"
          >
            <TrashIcon className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 px-5 py-4 sm:grid-cols-5">
        <Stat label="Rings" value={run.rings_detected} />
        <Stat
          label="Invoice mills"
          value={run.mills_detected}
          tone="warn"
          hint="sellers with no loop"
        />
        <Stat label="High risk" value={run.high_risk_count} tone="danger" />
        <Stat label="Confirmed" value={run.confirmed_count} tone="danger" />
        <Stat label="Cleared" value={run.dismissed_count} tone="good" />
      </div>

      <div className="px-5 pb-4">
        <div className="flex items-center justify-between text-[11px] text-zinc-500">
          <span>
            {reviewed} of {total} reviewed
          </span>
          <span>{formatInr(run.total_value_at_risk)} at risk</span>
        </div>
        <Progress
          value={reviewed}
          max={total || 1}
          tone={complete ? 'brand' : 'warn'}
          className="mt-1.5"
        />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-zinc-200 px-5 py-2.5 dark:border-zinc-800">
        <Mono>model {run.model_version || 'n/a'}</Mono>
        <Mono>threshold {Number(run.risk_threshold).toFixed(0)}</Mono>
        <Mono>{run.companies_scored} companies scored</Mono>
        {run.report_count > 0 && (
          <Link to="/reports" className="ml-auto">
            <Mono className="text-brand-600 hover:underline dark:text-brand-300">
              {run.report_count} report{run.report_count === 1 ? '' : 's'} issued →
            </Mono>
          </Link>
        )}
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Dialogs
//
// The modal chrome itself (`Dialog`) moved to components/ui.jsx once the
// report send-confirmation flow needed the exact same thing - a title, a
// close button, a footer for actions - and duplicating it a second time
// would have meant two things to keep visually in sync by hand.
// ---------------------------------------------------------------------------

function RunDialog({ onClose, onRun }) {
  const [name, setName] = useState('')
  return (
    <Dialog
      title="Name this detection run"
      subtitle="Runs are kept permanently, so a name you will recognise later helps. Leave it blank and it will be numbered."
      onClose={onClose}
      footer={
        <div className="flex gap-2">
          <Button variant="primary" className="flex-1" onClick={() => onRun(name.trim())}>
            Run detection
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </div>
      }
    >
      <Field label="Run name">
        <Input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && onRun(name.trim())}
          placeholder="e.g. After adding May filings"
        />
      </Field>
    </Dialog>
  )
}

function DropZone({ label, hint, file, onChange }) {
  const inputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)
  const take = (list) => list?.[0] && onChange(list[0])

  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-zinc-700 dark:text-zinc-300">{label}</div>
      {!file ? (
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            take(e.dataTransfer.files)
          }}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-7 text-center transition-colors ${
            dragOver
              ? 'border-brand-500 bg-brand-50 dark:bg-brand-900/20'
              : 'border-zinc-300 hover:border-zinc-400 dark:border-zinc-700 dark:hover:border-zinc-600'
          }`}
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-100 text-brand-700 dark:bg-brand-900/40 dark:text-brand-300">
            <UploadIcon className="h-4.5 w-4.5" />
          </span>
          <span className="text-sm font-medium text-brand-700 dark:text-brand-300">
            Choose a file or drag it here
          </span>
          <span className="text-[10px] leading-relaxed text-zinc-500">{hint}</span>
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => take(e.target.files)}
          />
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 dark:border-brand-800 dark:bg-brand-900/20">
          <span className="flex min-w-0 items-center gap-2 text-sm text-zinc-700 dark:text-zinc-200">
            <FileIcon className="h-4 w-4 shrink-0 text-brand-600 dark:text-brand-300" />
            <span className="truncate">{file.name}</span>
          </span>
          <button
            onClick={() => onChange(null)}
            aria-label={`Remove ${file.name}`}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white transition-colors hover:bg-brand-500"
          >
            <TrashIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  )
}

function UploadDialog({ onClose, onUploaded }) {
  const [companies, setCompanies] = useState(null)
  const [invoices, setInvoices] = useState(null)
  const [name, setName] = useState('')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)

  const submit = async () => {
    if (!companies || !invoices) return
    setUploading(true)
    setError(null)
    try {
      await uploadDataset(companies, invoices, name.trim())
      await onUploaded()
    } catch (e) {
      const errors = e?.response?.data?.errors
      setError(
        Array.isArray(errors) && errors.length
          ? errors.slice(0, 4).join(' · ')
          : e?.response?.data?.detail || e.message,
      )
    } finally {
      setUploading(false)
    }
  }

  return (
    <Dialog
      title="Upload a dataset"
      subtitle="Kept alongside your existing datasets — nothing is overwritten, and you can switch back to any of them later."
      onClose={onClose}
      footer={
        <Button
          variant="primary"
          className="w-full"
          onClick={submit}
          disabled={!companies || !invoices || uploading}
        >
          {uploading ? <Spinner /> : null}
          {uploading ? 'Uploading…' : 'Upload dataset'}
        </Button>
      }
    >
      <div className="space-y-4">
        <Field label="Name this dataset" hint="Optional — defaults to the upload date.">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Mumbai Zone — Q2 FY26"
          />
        </Field>
        <DropZone
          label="Companies CSV"
          hint="gstin, pan, name, director_name, registered_address, registered_date, declared_turnover"
          file={companies}
          onChange={setCompanies}
        />
        <DropZone
          label="Invoices CSV"
          hint="seller_gstin, buyer_gstin, amount, date, goods_description, has_eway_bill"
          file={invoices}
          onChange={setInvoices}
        />
        {error && <Banner tone="danger">{error}</Banner>}

        <p className="border-t border-zinc-200 pt-3 text-[11px] leading-relaxed text-zinc-500 dark:border-zinc-800">
          No data to hand?{' '}
          <a
            href="/lab"
            target="_blank"
            rel="noreferrer"
            className="font-medium text-brand-700 underline-offset-2 hover:underline dark:text-brand-300"
          >
            The Dataset Lab
          </a>{' '}
          fabricates a companies/invoices pair with a mix of obvious fraud, borderline cases and
          honest businesses — and tells you what the detector makes of it before you upload.
        </p>
      </div>
    </Dialog>
  )
}
