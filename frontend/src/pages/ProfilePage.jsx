import { useState } from 'react'
import { changePassword, setToken, updateProfile } from '../api'
import { useAuth } from '../useAuth.jsx'
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  CardHeader,
  Field,
  formatWhen,
  Input,
  Mono,
  PageHeader,
  Spinner,
} from '../components/ui.jsx'
import { CheckIcon, ShieldIcon } from '../icons.jsx'

/** Your own account: who you are, what you may do, and your password. */
export default function ProfilePage() {
  const { profile, isSupervisor, setProfile, can } = useAuth()

  if (!profile) return null

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-6">
        <PageHeader title="Your profile" />

        <Card className="mb-4">
          <div className="flex flex-wrap items-center gap-4 px-5 py-5">
            <Avatar name={profile.full_name} size="lg" className="h-14 w-14 text-lg" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-base font-semibold text-zinc-900 dark:text-zinc-50">
                  {profile.full_name}
                </h2>
                <Badge tone={isSupervisor ? 'good' : 'neutral'}>
                  {isSupervisor && <ShieldIcon className="h-2.5 w-2.5" />}
                  {profile.role_label}
                </Badge>
              </div>
              <p className="truncate text-xs text-zinc-500">@{profile.username}</p>
              <p className="mt-1 text-[11px] text-zinc-500">
                Joined {formatWhen(profile.date_joined)} · last signed in{' '}
                {formatWhen(profile.last_login)}
              </p>
            </div>
          </div>

          <div className="border-t border-zinc-200 px-5 py-4 dark:border-zinc-800">
            <p className="text-[11px] font-medium uppercase tracking-[0.09em] text-zinc-500">
              What you can do
            </p>
            <ul className="mt-2 grid gap-1.5 text-xs text-zinc-600 sm:grid-cols-2 dark:text-zinc-400">
              <Permission ok>Review alerts and read the evidence</Permission>
              <Permission ok>Clear an alert as not fraud</Permission>
              <Permission ok={can.can_run_detection}>Run detection</Permission>
              <Permission ok={can.can_issue_report}>Issue case reports</Permission>
              <Permission ok={can.can_confirm}>Confirm an alert as fraudulent</Permission>
              <Permission ok={can.can_view_team}>See the whole team's activity</Permission>
              <Permission ok={can.can_edit_settings}>Change detection settings</Permission>
            </ul>
            {!isSupervisor && (
              <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
                Confirming an alert starts recovery proceedings against a real business, so it
                is the one decision reserved for a supervisor. You prepare the case; they
                sanction it.
              </p>
            )}
          </div>
        </Card>

        <DetailsCard profile={profile} onSaved={setProfile} />
        <PasswordCard />
      </div>
    </div>
  )
}

function Permission({ ok, children }) {
  return (
    <li className="flex gap-2">
      <span className={ok ? 'text-brand-600 dark:text-brand-400' : 'text-zinc-400 dark:text-zinc-600'}>
        {ok ? '✓' : '✕'}
      </span>
      <span className={ok ? '' : 'text-zinc-400 dark:text-zinc-600'}>{children}</span>
    </li>
  )
}

function DetailsCard({ profile, onSaved }) {
  const [form, setForm] = useState({
    first_name: profile.first_name,
    last_name: profile.last_name,
    email: profile.email,
  })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  const dirty =
    form.first_name !== profile.first_name ||
    form.last_name !== profile.last_name ||
    form.email !== profile.email

  const save = async () => {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      onSaved(await updateProfile(form))
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader
        title="Your details"
        subtitle="Your email is where your copy of every case report is sent."
        actions={
          <Button variant="primary" size="sm" onClick={save} disabled={!dirty || saving}>
            {saving ? <Spinner /> : saved ? <CheckIcon className="h-4 w-4" /> : null}
            {saving ? 'Saving…' : saved ? 'Saved' : 'Save'}
          </Button>
        }
      />
      <div className="space-y-4 px-5 py-4">
        {!profile.email && (
          <Banner tone="warn">
            This account has no email address, so your copy of each case report has nowhere to
            go. Supervisors still receive theirs.
          </Banner>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="First name">
            <Input
              value={form.first_name}
              onChange={(e) => setForm({ ...form, first_name: e.target.value })}
            />
          </Field>
          <Field label="Last name">
            <Input
              value={form.last_name}
              onChange={(e) => setForm({ ...form, last_name: e.target.value })}
            />
          </Field>
        </div>
        <Field label="Email address">
          <Input
            type="email"
            value={form.email}
            placeholder="officer@department.gov.in"
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </Field>
        <p className="text-[11px] text-zinc-500">
          Your username <Mono>{profile.username}</Mono> identifies you in the audit ledger and
          cannot be changed here — it is part of the evidentiary record.
        </p>
        {error && <Banner tone="danger">{error}</Banner>}
      </div>
    </Card>
  )
}

function PasswordCard() {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' })
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState(null)

  const mismatch = form.next && form.confirm && form.next !== form.confirm
  const ready = form.current && form.next.length >= 8 && !mismatch

  const submit = async () => {
    setSaving(true)
    setError(null)
    try {
      const data = await changePassword(form.current, form.next)
      // The old token was revoked server-side; keep this session signed in.
      if (data.token) setToken(data.token)
      setForm({ current: '', next: '', confirm: '' })
      setDone(true)
      setTimeout(() => setDone(false), 4000)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader
        title="Password"
        subtitle="Changing it signs out every other device. This one stays signed in."
        actions={
          <Button variant="primary" size="sm" onClick={submit} disabled={!ready || saving}>
            {saving ? <Spinner /> : done ? <CheckIcon className="h-4 w-4" /> : null}
            {saving ? 'Changing…' : done ? 'Changed' : 'Change password'}
          </Button>
        }
      />
      <div className="space-y-4 px-5 py-4">
        <Field label="Current password">
          <Input
            type="password"
            autoComplete="current-password"
            value={form.current}
            onChange={(e) => setForm({ ...form, current: e.target.value })}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="New password" hint="At least 8 characters.">
            <Input
              type="password"
              autoComplete="new-password"
              value={form.next}
              onChange={(e) => setForm({ ...form, next: e.target.value })}
            />
          </Field>
          <Field label="Confirm new password">
            <Input
              type="password"
              autoComplete="new-password"
              value={form.confirm}
              onChange={(e) => setForm({ ...form, confirm: e.target.value })}
            />
          </Field>
        </div>
        {mismatch && <Banner tone="warn">The two new passwords do not match.</Banner>}
        {error && <Banner tone="danger">{error}</Banner>}
      </div>
    </Card>
  )
}
