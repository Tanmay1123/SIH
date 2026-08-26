/**
 * Shared interface primitives.
 *
 * These exist so spacing, radius, weight and colour are decided once instead
 * of being re-improvised in every screen - which is what makes an interface
 * look assembled rather than designed. Every page below builds out of these.
 */

export const cx = (...parts) => parts.filter(Boolean).join(' ')

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export const formatInr = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`
  return `₹${n.toLocaleString('en-IN')}`
}

export const formatWhen = (iso) =>
  iso
    ? new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
    : '—'

export const formatDay = (iso) =>
  iso ? new Date(iso).toLocaleDateString('en-IN', { dateStyle: 'medium' }) : '—'

export function relativeTime(iso) {
  if (!iso) return 'never'
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`
  return formatDay(iso)
}

// ---------------------------------------------------------------------------
// Surfaces
// ---------------------------------------------------------------------------

export function Card({ className, children, ...rest }) {
  return (
    <div
      className={cx(
        'rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  )
}

export function CardHeader({ title, subtitle, actions, className }) {
  return (
    <div
      className={cx(
        'flex items-start justify-between gap-4 border-b border-zinc-200 px-5 py-4 dark:border-zinc-800',
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-zinc-500">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pb-5">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-zinc-500">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

const BUTTON_VARIANTS = {
  primary:
    'bg-brand-600 text-white hover:bg-brand-500 disabled:hover:bg-brand-600 shadow-sm',
  danger: 'bg-red-700 text-white hover:bg-red-600 disabled:hover:bg-red-700 shadow-sm',
  outline:
    'border border-zinc-300 text-zinc-700 hover:border-zinc-400 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-zinc-600 dark:hover:bg-zinc-800',
  ghost:
    'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100',
  subtle:
    'bg-zinc-900 text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white',
}

const BUTTON_SIZES = {
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-9 px-4 text-sm gap-2',
  lg: 'h-11 px-5 text-sm gap-2',
}

export function Button({
  variant = 'outline',
  size = 'md',
  className,
  children,
  ...rest
}) {
  return (
    <button
      className={cx(
        'inline-flex select-none items-center justify-center rounded-lg font-medium transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-50',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Input({ className, ...rest }) {
  return (
    <input
      className={cx(
        'w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900',
        'outline-none transition-colors placeholder:text-zinc-400',
        'focus:border-brand-500 focus:ring-2 focus:ring-brand-500/15',
        'disabled:opacity-60',
        'dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder:text-zinc-600',
        className,
      )}
      {...rest}
    />
  )
}

export function Select({ className, children, ...rest }) {
  return (
    <select
      className={cx(
        'w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900',
        'outline-none transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/15',
        'dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100',
        className,
      )}
      {...rest}
    >
      {children}
    </select>
  )
}

export function Textarea({ className, ...rest }) {
  return (
    <textarea
      className={cx(
        'w-full resize-none rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900',
        'outline-none transition-colors placeholder:text-zinc-400',
        'focus:border-brand-500 focus:ring-2 focus:ring-brand-500/15',
        'dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder:text-zinc-600',
        className,
      )}
      {...rest}
    />
  )
}

export function Field({ label, hint, children, className }) {
  return (
    <label className={cx('block', className)}>
      <span className="mb-1.5 block text-xs font-medium text-zinc-700 dark:text-zinc-300">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1.5 block text-[11px] leading-relaxed text-zinc-500">{hint}</span>}
    </label>
  )
}

// ---------------------------------------------------------------------------
// Data display
// ---------------------------------------------------------------------------

const TONES = {
  default: 'text-zinc-900 dark:text-zinc-100',
  muted: 'text-zinc-500',
  danger: 'text-red-600 dark:text-red-400',
  warn: 'text-amber-600 dark:text-amber-400',
  good: 'text-brand-600 dark:text-brand-300',
}

export function Stat({ label, value, tone = 'default', hint, className }) {
  return (
    <div className={cx('min-w-0', className)}>
      <div className="text-[10px] font-medium uppercase tracking-[0.09em] text-zinc-500">
        {label}
      </div>
      <div className={cx('mt-1 truncate text-2xl font-semibold tabular tracking-tight', TONES[tone])}>
        {value}
      </div>
      {hint && <div className="mt-0.5 truncate text-[11px] text-zinc-500">{hint}</div>}
    </div>
  )
}

const BADGE_TONES = {
  neutral:
    'border-zinc-200 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400',
  danger:
    'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300',
  warn: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300',
  good: 'border-brand-200 bg-brand-50 text-brand-700 dark:border-brand-800 dark:bg-brand-900/50 dark:text-brand-200',
  info: 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-300',
}

export function Badge({ tone = 'neutral', className, children }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em]',
        BADGE_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Progress({ value, max = 1, tone = 'brand', className }) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0
  const fill = tone === 'brand' ? 'bg-brand-500' : tone === 'warn' ? 'bg-amber-500' : 'bg-zinc-400'
  return (
    <div className={cx('h-1.5 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800', className)}>
      <div className={cx('h-full rounded-full transition-all', fill)} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Mono({ className, children }) {
  return (
    <span className={cx('font-mono text-[11px] text-zinc-500', className)}>{children}</span>
  )
}

export function EmptyState({ icon, title, children, action }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      {icon && (
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-zinc-100 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-500">
          {icon}
        </span>
      )}
      <div>
        <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{title}</p>
        {children && (
          <p className="mx-auto mt-1.5 max-w-md text-xs leading-relaxed text-zinc-500">
            {children}
          </p>
        )}
      </div>
      {action}
    </div>
  )
}

export function Banner({ tone = 'info', className, children }) {
  const tones = {
    info: 'border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300',
    good: 'border-brand-200 bg-brand-50 text-brand-800 dark:border-brand-800 dark:bg-brand-900/40 dark:text-brand-200',
    warn: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-200',
    danger:
      'border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/60 dark:text-red-200',
  }
  return (
    <div
      className={cx(
        'flex items-start gap-2.5 rounded-lg border px-3.5 py-2.5 text-xs leading-relaxed',
        tones[tone],
        className,
      )}
    >
      {children}
    </div>
  )
}

export function Spinner({ className }) {
  return (
    <span
      className={cx(
        'inline-block animate-spin rounded-full border-2 border-current border-t-transparent',
        className || 'h-4 w-4',
      )}
      aria-hidden="true"
    />
  )
}

export function Avatar({ name, size = 'md', className }) {
  const initials = (name || '?')
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('')
  const sizes = { sm: 'h-6 w-6 text-[10px]', md: 'h-8 w-8 text-xs', lg: 'h-12 w-12 text-base' }
  return (
    <span
      className={cx(
        'flex shrink-0 items-center justify-center rounded-full bg-zinc-200 font-semibold text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200',
        sizes[size],
        className,
      )}
    >
      {initials || '?'}
    </span>
  )
}

/** Risk colouring, shared by every surface that shows a score. */
export function riskTone(score, threshold = 70) {
  if (score >= threshold) return 'danger'
  if (score >= threshold * 0.57) return 'warn'
  if (score > 0) return 'good'
  return 'neutral'
}

export function riskTextClass(score, threshold = 70) {
  return TONES[riskTone(score, threshold) === 'neutral' ? 'muted' : riskTone(score, threshold)]
}
