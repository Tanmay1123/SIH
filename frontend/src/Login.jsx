import { useState } from 'react'
import { login, setToken } from './api'

/**
 * Gate in front of the whole console. Only an account created by an admin
 * (`python manage.py createsuperuser`, or added in /admin/) can get in - there
 * is no self-signup, on purpose: this is a tool for authorised government
 * officers, not a public product.
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
      onAuthenticated(data.username)
    } catch (err) {
      setError(
        err?.response?.status === 401
          ? 'Incorrect username or password.'
          : err?.response?.data?.detail || 'Could not reach the API.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-200">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900"
      >
        <h1 className="text-base font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
          GST Circular-Trade Fraud Detection
        </h1>
        <p className="mt-1 text-xs text-zinc-500">
          Restricted access. Authorised government officers only.
        </p>

        <div className="mt-5 space-y-3">
          <div>
            <label className="mb-1 block text-[11px] font-medium tracking-wide text-zinc-500">
              USERNAME
            </label>
            <input
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:border-green-600 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium tracking-wide text-zinc-500">
              PASSWORD
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:border-green-600 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
            />
          </div>
        </div>

        {error && <p className="mt-3 text-xs text-red-600 dark:text-red-400">{error}</p>}

        <button
          type="submit"
          disabled={submitting || !username || !password}
          className="mt-5 w-full rounded bg-green-700 px-4 py-2 text-sm font-medium text-white hover:bg-green-600 disabled:opacity-50"
        >
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="mt-4 text-[10px] leading-relaxed text-zinc-500 dark:text-zinc-600">
          No account? Officer accounts are created by an administrator via{' '}
          <code className="text-zinc-600 dark:text-zinc-500">python manage.py createsuperuser</code>{' '}
          or the Django admin at <code className="text-zinc-600 dark:text-zinc-500">/admin/</code>.
        </p>
      </form>
    </div>
  )
}
