import { Link } from 'react-router-dom'
import { useAuth } from '../useAuth.jsx'
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
  Progress,
  Stat,
} from '../components/ui.jsx'
import {
  AlertIcon,
  ChainIcon,
  DatabaseIcon,
  HubIcon,
  LoopIcon,
  ShieldIcon,
  UploadIcon,
} from '../icons.jsx'

/**
 * Where an officer lands: what is loaded, what the last run found, and what is
 * still waiting on a human. The counters that used to be crammed into the
 * header strip live here instead, where they have room to be read.
 */
export default function OverviewPage({ status, rings, onRunDetection, running, loading }) {
  const { profile, can, isSupervisor } = useAuth()

  const threshold = status?.risk_threshold ?? 70
  const hasData = (status?.companies ?? 0) > 0
  const hasRun = Boolean(status?.run)
  const pending = status?.rings_pending ?? 0
  const reviewed = (status?.rings_confirmed ?? 0) + (status?.rings_dismissed ?? 0)
  const total = pending + reviewed

  const topAlerts = [...(rings || [])]
    .filter((r) => r.status === 'pending')
    .sort((a, b) => b.risk_score - a.risk_score)
    .slice(0, 6)

  const valueAtRisk = (rings || [])
    .filter((r) => r.risk_score >= threshold)
    .reduce((sum, r) => sum + Number(r.total_cycle_value || 0), 0)

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-6 py-6">
        <PageHeader
          title={`Good to see you, ${profile?.first_name || profile?.username}`}
          subtitle={
            hasRun
              ? `Showing ${status.run.name}. Alerts are candidates, not verdicts — each one still needs a human.`
              : 'Upload a companies and invoices CSV pair, then run detection to begin.'
          }
          actions={
            hasData && can.can_run_detection ? (
              <Button variant="primary" onClick={onRunDetection} disabled={running}>
                {running ? 'Running…' : hasRun ? 'Run detection again' : 'Run detection'}
              </Button>
            ) : null
          }
        />

        {!hasData && !loading && (
          <Card>
            <EmptyState
              icon={<UploadIcon className="h-5 w-5" />}
              title="No dataset loaded yet"
              action={
                <Link to="/detections">
                  <Button variant="primary" size="sm">
                    Go to Detections to upload
                  </Button>
                </Link>
              }
            >
              The console holds no data of its own. Upload a companies CSV and an invoices
              CSV and they become a dataset you can run detection against.
            </EmptyState>
          </Card>
        )}

        {hasData && (
          <>
            {/* ---- headline numbers ---- */}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Card className="p-5">
                <Stat
                  label="Awaiting review"
                  value={pending}
                  tone={pending > 0 ? 'warn' : 'good'}
                  hint={total > 0 ? `${reviewed} of ${total} decided` : 'nothing detected yet'}
                />
                {total > 0 && (
                  <Progress
                    value={reviewed}
                    max={total}
                    tone={reviewed === total ? 'brand' : 'warn'}
                    className="mt-3"
                  />
                )}
              </Card>

              <Card className="p-5">
                <Stat
                  label="High risk"
                  value={status?.high_risk_rings ?? '—'}
                  tone="danger"
                  hint={`scoring ${Number(threshold).toFixed(0)} or above`}
                />
              </Card>

              <Card className="p-5">
                <Stat
                  label="Value at risk"
                  value={formatInr(valueAtRisk)}
                  hint="across high-risk alerts"
                />
              </Card>

              <Card className="p-5">
                <Stat
                  label="Audit ledger"
                  value={status?.ledger?.valid ? 'Intact' : 'BROKEN'}
                  tone={status?.ledger?.valid ? 'good' : 'danger'}
                  hint={`${status?.ledger?.block_count ?? 0} blocks`}
                />
              </Card>
            </div>

            {/* ---- what was found ---- */}
            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <CardHeader
                  title="What this run found"
                  subtitle="Two detectors, two different shapes of fraud."
                  actions={
                    <Link to="/network">
                      <Button size="sm" variant="outline">
                        Open network
                      </Button>
                    </Link>
                  }
                />
                <div className="grid gap-px bg-zinc-200 sm:grid-cols-2 dark:bg-zinc-800">
                  <DetectorPanel
                    icon={<LoopIcon className="h-4 w-4" />}
                    title="Circular-trade rings"
                    count={status?.rings_detected ?? 0}
                    blurb="Closed invoice loops — including loops that close through a shared director or registered address rather than through a bill."
                  />
                  <DetectorPanel
                    icon={<HubIcon className="h-4 w-4" />}
                    title="Fake invoice mills"
                    count={status?.mills_detected ?? 0}
                    tone="warn"
                    blurb="A shell selling to many buyers and buying from nobody. Not a loop at all, so cycle detection is blind to it."
                  />
                </div>
              </Card>

              <Card>
                <CardHeader title="Your access" />
                <div className="space-y-3 px-5 py-4">
                  <Badge tone={isSupervisor ? 'good' : 'neutral'}>
                    {isSupervisor && <ShieldIcon className="h-2.5 w-2.5" />}
                    {profile?.role_label}
                  </Badge>
                  <ul className="space-y-2 text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                    <Capability ok>Review alerts and see the evidence</Capability>
                    <Capability ok>Clear an alert as not fraud</Capability>
                    <Capability ok={can.can_issue_report}>Issue case reports</Capability>
                    <Capability ok={can.can_confirm}>Confirm an alert as fraudulent</Capability>
                    <Capability ok={can.can_view_team}>See every officer’s activity</Capability>
                  </ul>
                </div>
              </Card>
            </div>

            {/* ---- queue preview ---- */}
            <Card className="mt-4">
              <CardHeader
                title="Top of your queue"
                subtitle="Highest-risk alerts nobody has ruled on yet."
                actions={
                  <Link to="/network">
                    <Button size="sm" variant="outline">
                      Review all
                    </Button>
                  </Link>
                }
              />
              {topAlerts.length === 0 ? (
                <EmptyState
                  icon={<AlertIcon className="h-5 w-5" />}
                  title={hasRun ? 'Nothing left to review' : 'No detection run yet'}
                >
                  {hasRun
                    ? 'Every alert in this run has been confirmed or cleared. Issue a case report from the Reports page.'
                    : 'Run detection to search this dataset for circular trading and invoice mills.'}
                </EmptyState>
              ) : (
                <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {topAlerts.map((alert) => (
                    <li key={alert.id}>
                      <Link
                        to={`/network?alert=${alert.id}`}
                        className="flex items-center gap-3 px-5 py-3 transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                      >
                        <span
                          className={
                            alert.kind === 'mill'
                              ? 'text-amber-600 dark:text-amber-400'
                              : 'text-zinc-400'
                          }
                        >
                          {alert.kind === 'mill' ? (
                            <HubIcon className="h-4 w-4" />
                          ) : (
                            <LoopIcon className="h-4 w-4" />
                          )}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">
                              {alert.kind === 'mill' ? 'Mill' : 'Ring'} {alert.id}
                            </span>
                            {alert.closure === 'control' && (
                              <Badge tone="warn">shared ownership</Badge>
                            )}
                          </span>
                          <span className="mt-0.5 block truncate text-xs text-zinc-500">
                            {(alert.company_names || []).slice(0, 4).join(' → ')}
                          </span>
                        </span>
                        <span className="shrink-0 text-right">
                          <span className="block text-sm font-semibold tabular text-red-600 dark:text-red-400">
                            {alert.risk_score.toFixed(1)}
                          </span>
                          <span className="block text-[11px] text-zinc-500">
                            {formatInr(alert.total_cycle_value)}
                          </span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {/* ---- provenance ---- */}
            {hasRun && (
              <Banner tone="info" className="mt-4">
                <ChainIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Scored by model{' '}
                  <Mono className="text-zinc-700 dark:text-zinc-300">
                    {status.run.model_version || 'n/a'}
                  </Mono>{' '}
                  at threshold {Number(threshold).toFixed(0)}, run {formatWhen(status.run.started_at)}.
                  Every decision records that provenance in the ledger, so a flag can always be
                  traced back to the model that produced it.
                </span>
              </Banner>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function DetectorPanel({ icon, title, count, blurb, tone = 'default' }) {
  return (
    <div className="bg-white px-5 py-4 dark:bg-zinc-900">
      <div className="flex items-center gap-2">
        <span className={tone === 'warn' ? 'text-amber-600 dark:text-amber-400' : 'text-zinc-400'}>
          {icon}
        </span>
        <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300">{title}</span>
      </div>
      <div className="mt-2 text-3xl font-semibold tabular tracking-tight text-zinc-900 dark:text-zinc-50">
        {count}
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">{blurb}</p>
    </div>
  )
}

function Capability({ ok, children }) {
  return (
    <li className="flex gap-2">
      <span
        className={
          ok
            ? 'mt-0.5 shrink-0 text-brand-600 dark:text-brand-400'
            : 'mt-0.5 shrink-0 text-zinc-400 dark:text-zinc-600'
        }
      >
        {ok ? '✓' : '✕'}
      </span>
      <span className={ok ? '' : 'text-zinc-400 dark:text-zinc-600'}>{children}</span>
    </li>
  )
}
