import { useCallback, useEffect, useState } from 'react'
import { getTeam, getTeamActivity, setMemberRole } from '../api'
import { useAuth } from '../useAuth.jsx'
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  CardHeader,
  EmptyState,
  formatWhen,
  Mono,
  PageHeader,
  relativeTime,
  Select,
  Stat,
} from '../components/ui.jsx'
import {
  CheckIcon,
  CloseIcon,
  DocumentIcon,
  PulseIcon,
  ShieldIcon,
  UsersIcon,
} from '../icons.jsx'

/**
 * The supervisor's view of the team.
 *
 * The reason the supervisor role exists: someone has to sanction cases, and to
 * do that responsibly they need to see who is preparing them, how much of the
 * queue each officer has worked through, and - just as importantly - what has
 * been cleared rather than pursued.
 *
 * Officers never see this page; the API refuses it for them regardless.
 */
export default function TeamPage() {
  const { profile } = useAuth()
  const [team, setTeam] = useState(null)
  const [activity, setActivity] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [teamData, activityData] = await Promise.all([getTeam(), getTeamActivity(50)])
      setTeam(teamData)
      setActivity(activityData)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleRole = async (member, role) => {
    setBusy(member.id)
    setError(null)
    try {
      await setMemberRole(member.id, role)
      await load()
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(null)
    }
  }

  const totals = team?.totals

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-6 py-6">
        <PageHeader
          title="Team"
          subtitle="Who is working the queue, and what they have decided. An officer prepares and clears cases; confirming one as fraudulent is yours."
        />

        {error && (
          <Banner tone="danger" className="mb-4">
            {error}
          </Banner>
        )}

        {totals && (
          <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <Card className="p-5">
              <Stat label="Officers" value={totals.officers} />
            </Card>
            <Card className="p-5">
              <Stat label="Supervisors" value={totals.supervisors} tone="good" />
            </Card>
            <Card className="p-5">
              <Stat
                label="Awaiting review"
                value={totals.pending_review}
                tone={totals.pending_review > 0 ? 'warn' : 'good'}
                hint="all runs"
              />
            </Card>
            <Card className="p-5">
              <Stat label="Confirmed" value={totals.confirmed} tone="danger" hint="all runs" />
            </Card>
            <Card className="p-5">
              <Stat label="Cleared" value={totals.dismissed} tone="good" hint="all runs" />
            </Card>
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-5">
          {/* ---- members ---- */}
          <Card className="lg:col-span-3">
            <CardHeader
              title="Accounts"
              subtitle="Change a role here, or add accounts in the Django admin."
            />
            {loading && <div className="p-6 text-sm text-zinc-500">Loading team…</div>}

            {!loading && !team?.members?.length && (
              <EmptyState icon={<UsersIcon className="h-5 w-5" />} title="No accounts found" />
            )}

            <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {(team?.members || []).map((member) => (
                <li key={member.id} className="flex flex-wrap items-start gap-3 px-5 py-4">
                  <Avatar name={member.full_name} size="lg" />

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">
                        {member.full_name}
                      </span>
                      <Badge tone={member.role === 'supervisor' ? 'good' : 'neutral'}>
                        {member.role === 'supervisor' && <ShieldIcon className="h-2.5 w-2.5" />}
                        {member.role_label}
                      </Badge>
                      {member.id === profile?.id && <Badge tone="info">You</Badge>}
                      {member.is_superuser && <Badge tone="info">Superuser</Badge>}
                    </div>
                    <p className="truncate text-[11px] text-zinc-500">
                      @{member.username}
                      {member.email ? ` · ${member.email}` : ' · no email set'}
                    </p>

                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
                      <span>
                        <strong className="text-red-600 dark:text-red-400">
                          {member.activity.confirmed}
                        </strong>{' '}
                        confirmed
                      </span>
                      <span>
                        <strong className="text-brand-600 dark:text-brand-300">
                          {member.activity.dismissed}
                        </strong>{' '}
                        cleared
                      </span>
                      <span>
                        <strong className="text-zinc-700 dark:text-zinc-300">
                          {member.activity.runs}
                        </strong>{' '}
                        runs
                      </span>
                      <span>
                        <strong className="text-zinc-700 dark:text-zinc-300">
                          {member.activity.reports}
                        </strong>{' '}
                        reports
                      </span>
                      <span>last decision {relativeTime(member.activity.last_decision_at)}</span>
                    </div>
                  </div>

                  <div className="shrink-0">
                    <Select
                      value={member.role}
                      disabled={busy === member.id || member.id === profile?.id || member.is_superuser}
                      onChange={(e) => handleRole(member, e.target.value)}
                      className="w-36 py-1.5 text-xs"
                      title={
                        member.id === profile?.id
                          ? 'You cannot change your own role'
                          : member.is_superuser
                            ? 'Superusers are always supervisors'
                            : 'Change this account’s role'
                      }
                    >
                      <option value="officer">Officer</option>
                      <option value="supervisor">Supervisor</option>
                    </Select>
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          {/* ---- activity ---- */}
          <Card className="lg:col-span-2">
            <CardHeader
              title="Recent activity"
              subtitle="Decisions, runs and issued reports across the whole team."
            />
            {!loading && activity.length === 0 && (
              <EmptyState icon={<PulseIcon className="h-5 w-5" />} title="Nothing has happened yet" />
            )}
            <ul className="max-h-[32rem] divide-y divide-zinc-200 overflow-y-auto dark:divide-zinc-800">
              {activity.map((event, i) => (
                <li key={`${event.kind}-${event.at}-${i}`} className="flex gap-3 px-5 py-3">
                  <EventIcon kind={event.kind} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-zinc-800 dark:text-zinc-200">
                      {event.title}
                    </p>
                    <p className="truncate text-[11px] text-zinc-500">{event.detail}</p>
                    {event.note && (
                      <p className="mt-0.5 truncate text-[11px] italic text-zinc-500">
                        “{event.note}”
                      </p>
                    )}
                    <p className="mt-0.5 text-[10px] text-zinc-400 dark:text-zinc-600">
                      {event.actor} · {relativeTime(event.at)}
                      {event.run && ` · ${event.run}`}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        {team && (
          <p className="mt-4 text-[11px] leading-relaxed text-zinc-500">
            Role membership is the Django group <Mono>{team.supervisor_group}</Mono>, so it can
            also be administered from <Mono>/admin/</Mono>. New accounts are created there or
            with <Mono>manage.py createsuperuser</Mono> — there is no self-signup, on purpose.
          </p>
        )}
      </div>
    </div>
  )
}

function EventIcon({ kind }) {
  const map = {
    confirmed: {
      icon: <CheckIcon className="h-3 w-3" />,
      cls: 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300',
    },
    dismissed: {
      icon: <CloseIcon className="h-3 w-3" />,
      cls: 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400',
    },
    run: {
      icon: <PulseIcon className="h-3 w-3" />,
      cls: 'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300',
    },
    report: {
      icon: <DocumentIcon className="h-3 w-3" />,
      cls: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
    },
  }
  const { icon, cls } = map[kind] || map.run
  return (
    <span
      className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${cls}`}
    >
      {icon}
    </span>
  )
}
