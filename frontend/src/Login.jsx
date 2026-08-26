import { useState } from 'react'
import { login, setToken } from './api'
import { Banner, Button, Field, Input, Mono, Spinner } from './components/ui.jsx'
import { NetworkIcon, ShieldIcon } from './icons.jsx'

/**
 * Gate in front of the whole console.
 *
 * Only an account created by an administrator (`manage.py createsuperuser`, or
 * added in /admin/) can get in - there is no self-signup, on purpose: this is a
 * tool for authorised officers, not a public product.
 */
export default function Login({ onAuthenticated }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const data = await login(username, password)
      setToken(data.token)
      await onAuthenticated()
    } catch (err) {
      setError(
        err?.response?.status === 401
          ? 'Incorrect username or password.'
          : err?.response?.data?.detail || 'Could not reach the API. Is the backend running?',
      )
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen bg-zinc-50 dark:bg-zinc-950">
      {/* ---- the pitch, on wide screens ---- */}
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden bg-zinc-900 p-12 lg:flex dark:bg-zinc-900">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-[0.14]"
          style={{
            backgroundImage:
              'radial-gradient(circle at 20% 30%, #479f6a 0, transparent 42%), radial-gradient(circle at 78% 68%, #dc2626 0, transparent 40%)',
          }}
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-[0.06]"
          style={{
            backgroundImage:
              'linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)',
            backgroundSize: '44px 44px',
          }}
        />

        <div className="relative flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
            <NetworkIcon className="h-4.5 w-4.5" />
          </span>
          <span className="text-sm font-semibold tracking-tight text-zinc-100">
            Circular-Trade Fraud Detection
          </span>
        </div>

        <div className="relative max-w-md">
          <p className="text-2xl font-semibold leading-snug tracking-tight text-zinc-50">
            Every invoice in a fraud ring looks perfect on its own.
          </p>
          <p className="mt-4 text-sm leading-relaxed text-zinc-400">
            The fraud is only visible in the shape of the network — value that leaves a company
            and comes back to it, or a shell that sells to everyone and buys from nobody. This
            console finds those shapes, ranks them, explains them in plain English, and records
            every decision an officer makes in a tamper-evident ledger.
          </p>
        </div>

        <p className="relative text-[11px] leading-relaxed text-zinc-500">
          Smart India Hackathon 2026 · SIH26_95 · Nothing in this system blocks a refund
          automatically. Every enforcement action remains a human decision.
        </p>
      </div>

      {/* ---- the form ---- */}
      <div className="flex w-full items-center justify-center px-6 py-12 lg:w-1/2">
        <form onSubmit={handleSubmit} className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white">
              <NetworkIcon className="h-5 w-5" />
            </span>
          </div>

          <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            Sign in
          </h1>
          <p className="mt-1.5 flex items-center gap-1.5 text-xs text-zinc-500">
            <ShieldIcon className="h-3.5 w-3.5" />
            Restricted access — authorised officers only.
          </p>

          <div className="mt-7 space-y-4">
            <Field label="Username">
              <Input
                autoFocus
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </Field>
            <Field label="Password">
              <Input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
          </div>

          {error && (
            <Banner tone="danger" className="mt-4">
              {error}
            </Banner>
          )}

          <Button
            type="submit"
            variant="primary"
            size="lg"
            className="mt-6 w-full"
            disabled={submitting || !username || !password}
          >
            {submitting ? <Spinner /> : null}
            {submitting ? 'Signing in…' : 'Sign in'}
          </Button>

          <p className="mt-6 text-[11px] leading-relaxed text-zinc-500">
            No account? There is no self-signup. Officer accounts are created by an
            administrator with <Mono>python manage.py createsuperuser</Mono> or in the Django
            admin at <Mono>/admin/</Mono>.
          </p>
        </form>
      </div>
    </div>
  )
}
