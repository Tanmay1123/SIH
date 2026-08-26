import { useCallback, useEffect, useState } from 'react'
import { getSettings, updateSettings } from '../api'
import { useAuth } from '../useAuth.jsx'
import {
  Badge,
  Banner,
  Button,
  Card,
  CardHeader,
  Input,
  Mono,
  PageHeader,
  Spinner,
} from '../components/ui.jsx'
import { CheckIcon, SettingsIcon } from '../icons.jsx'

/**
 * Detection policy and report delivery, editable in the application.
 *
 * These used to be literals in the source - the risk threshold was the number
 * 70 written into two different files, and the supervisor address only existed
 * in `.env`. They are policy, not constants, so they belong somewhere an
 * administrator can reach.
 *
 * Resolution order is database, then `.env`, then a built-in default, and each
 * field says which of the three it is currently getting its value from.
 * Clearing a field falls back to the next one down.
 */
export default function SettingsPage() {
  const { can } = useAuth()
  const [fields, setFields] = useState([])
  const [draft, setDraft] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getSettings()
      setFields(data.settings)
      setDraft(Object.fromEntries(data.settings.map((s) => [s.key, s.value])))
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const dirty = fields.some((f) => String(draft[f.key] ?? '') !== String(f.value ?? ''))

  const save = async () => {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const changed = Object.fromEntries(
        fields
          .filter((f) => String(draft[f.key] ?? '') !== String(f.value ?? ''))
          .map((f) => [f.key, draft[f.key]]),
      )
      const data = await updateSettings(changed)
      setFields(data.settings)
      setDraft(Object.fromEntries(data.settings.map((s) => [s.key, s.value])))
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setSaving(false)
    }
  }

  const groups = [...new Set(fields.map((f) => f.group))]

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-6">
        <PageHeader
          title="Settings"
          subtitle={
            can.can_edit_settings
              ? 'Detection policy and report delivery. Changes take effect on the next detection run — past runs keep the values that were in force when they ran.'
              : 'The policy currently in force. Only a supervisor can change these.'
          }
          actions={
            can.can_edit_settings ? (
              <>
                {dirty && (
                  <Button variant="ghost" onClick={() => load()} disabled={saving}>
                    Discard
                  </Button>
                )}
                <Button variant="primary" onClick={save} disabled={!dirty || saving}>
                  {saving ? <Spinner /> : saved ? <CheckIcon className="h-4 w-4" /> : null}
                  {saving ? 'Saving…' : saved ? 'Saved' : 'Save changes'}
                </Button>
              </>
            ) : null
          }
        />

        {error && (
          <Banner tone="danger" className="mb-4">
            {error}
          </Banner>
        )}

        {!can.can_edit_settings && (
          <Banner tone="info" className="mb-4">
            <SettingsIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              You are signed in as an officer. These values shape every alert you see, so they
              are shown here — a supervisor changes them.
            </span>
          </Banner>
        )}

        {loading && <Card className="p-6 text-sm text-zinc-500">Loading settings…</Card>}

        <div className="space-y-4">
          {groups.map((group) => (
            <Card key={group}>
              <CardHeader title={group} />
              <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {fields
                  .filter((f) => f.group === group)
                  .map((field) => (
                    <SettingRow
                      key={field.key}
                      field={field}
                      value={draft[field.key] ?? ''}
                      editable={can.can_edit_settings}
                      onChange={(v) => setDraft((d) => ({ ...d, [field.key]: v }))}
                    />
                  ))}
              </div>
            </Card>
          ))}
        </div>

        <p className="mt-4 text-[11px] leading-relaxed text-zinc-500">
          Each value resolves in the order <strong>database → .env → built-in default</strong>.
          Clearing a field here removes the override, so it falls back to whatever{' '}
          <Mono>.env</Mono> says. Email credentials themselves stay in <Mono>.env</Mono> — they
          are secrets and do not belong in a database an application can read back.
        </p>
      </div>
    </div>
  )
}

function SettingRow({ field, value, editable, onChange }) {
  const sourceTone =
    field.source === 'database' ? 'good' : field.source === 'environment' ? 'info' : 'neutral'
  const sourceLabel =
    field.source === 'database'
      ? 'set here'
      : field.source === 'environment'
        ? 'from .env'
        : 'default'

  return (
    <div className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_16rem]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200">
            {field.label}
          </span>
          <Badge tone={sourceTone}>{sourceLabel}</Badge>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">{field.help}</p>
        <Mono className="mt-1 block">
          {field.env_var} · default {field.default || '(empty)'}
        </Mono>
      </div>

      <div className="sm:justify-self-end sm:self-start">
        <Input
          type={field.type === 'number' ? 'number' : 'text'}
          value={value}
          disabled={!editable}
          min={field.min}
          max={field.max}
          placeholder={field.default || 'not set'}
          onChange={(e) => onChange(e.target.value)}
          className="sm:w-64"
        />
      </div>
    </div>
  )
}
