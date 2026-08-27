import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import UserMenu from './UserMenu.jsx'
import DatasetPicker from '../components/DatasetPicker.jsx'
import { useAuth } from '../useAuth.jsx'
import { Badge, cx } from '../components/ui.jsx'
import {
  ChainIcon,
  DocumentIcon,
  GridIcon,
  MenuIcon,
  MoonIcon,
  NetworkIcon,
  PulseIcon,
  SettingsIcon,
  SunIcon,
  UsersIcon,
} from '../icons.jsx'

/**
 * The application frame: a navigation rail, a context bar, and the page.
 *
 * Everything used to live on one screen behind three tabs, with the dataset
 * switcher, nine counters, two buttons and the account all competing for the
 * same header strip. Splitting it into real routed pages is what makes this
 * navigable rather than merely dense - each area now has room to be itself,
 * and the browser's own back button works.
 */

function navItems(can) {
  return [
    { to: '/', label: 'Overview', icon: GridIcon, end: true },
    { to: '/network', label: 'Network', icon: NetworkIcon },
    { to: '/detections', label: 'Detections', icon: PulseIcon },
    { to: '/reports', label: 'Reports', icon: DocumentIcon },
    { to: '/ledger', label: 'Audit ledger', icon: ChainIcon },
    ...(can.can_view_team ? [{ to: '/team', label: 'Team', icon: UsersIcon }] : []),
    { to: '/settings', label: 'Settings', icon: SettingsIcon },
  ]
}

/** Deliberately not in icons.jsx: it names a thing outside the console. */
function FlaskIcon({ className }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M10 3h4" />
      <path d="M10 3v6.5L4.6 18a2 2 0 0 0 1.7 3h11.4a2 2 0 0 0 1.7-3L14 9.5V3" />
      <path d="M6.8 14.5h10.4" />
    </svg>
  )
}

function ThemeToggle({ theme, onToggle }) {
  return (
    <button
      onClick={onToggle}
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
    >
      {theme === 'dark' ? <SunIcon className="h-4 w-4" /> : <MoonIcon className="h-4 w-4" />}
    </button>
  )
}

export default function AppShell({ theme, onToggleTheme, status, onRefresh, pendingCount }) {
  const { can, isSupervisor } = useAuth()
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem('codenova_nav_collapsed') === '1',
  )
  const location = useLocation()

  useEffect(() => {
    localStorage.setItem('codenova_nav_collapsed', collapsed ? '1' : '0')
  }, [collapsed])

  const items = navItems(can)
  const current = items.find((i) => (i.end ? location.pathname === i.to : location.pathname.startsWith(i.to)))

  return (
    <div className="flex h-screen overflow-hidden bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-200">
      {/* ---------------- navigation rail ---------------- */}
      <nav
        className={cx(
          'flex shrink-0 flex-col border-r border-zinc-200 bg-white transition-[width] duration-200 dark:border-zinc-800 dark:bg-zinc-900',
          collapsed ? 'w-16' : 'w-60',
        )}
      >
        <div
          className={cx(
            'flex h-16 items-center gap-2.5 border-b border-zinc-200 dark:border-zinc-800',
            collapsed ? 'justify-center px-2' : 'px-4',
          )}
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white">
            <NetworkIcon className="h-4.5 w-4.5" />
          </span>
          {!collapsed && (
            <span className="min-w-0">
              <span className="block truncate text-[13px] font-semibold leading-tight tracking-tight text-zinc-900 dark:text-zinc-50">
                Circular-Trade
              </span>
              <span className="block truncate text-[10px] leading-tight text-zinc-500">
                GST fraud detection
              </span>
            </span>
          )}
        </div>

        <div className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {items.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cx(
                  'relative flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors',
                  collapsed && 'justify-center px-0',
                  isActive
                    ? 'bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50'
                    : 'text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-200',
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r bg-brand-500" />
                  )}
                  <Icon className="h-4.5 w-4.5 shrink-0" />
                  {!collapsed && <span className="truncate">{label}</span>}
                  {!collapsed && to === '/network' && pendingCount > 0 && (
                    <span className="ml-auto rounded-md bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-900/60 dark:text-amber-300">
                      {pendingCount}
                    </span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </div>

        <div className="border-t border-zinc-200 p-2 dark:border-zinc-800">
          {/* Not one of the console's pages, and styled so it does not pretend
              to be: the lab makes fabricated data, and nothing it produces is a
              finding about a real business. Kept here only because it is what
              an empty console needs first. */}
          <a
            href="/lab"
            target="_blank"
            rel="noreferrer"
            title="Dataset Lab - generate fabricated test data (opens in a new tab)"
            className={cx(
              'mb-1 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium text-zinc-500 transition-colors hover:bg-zinc-50 hover:text-zinc-800 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-200',
              collapsed && 'justify-center px-0',
            )}
          >
            <FlaskIcon className="h-4.5 w-4.5 shrink-0" />
            {!collapsed && (
              <>
                <span className="truncate">Dataset lab</span>
                <span aria-hidden className="ml-auto text-[10px] text-zinc-400">↗</span>
              </>
            )}
          </a>
          {!collapsed && (
            <div className="mb-2 px-2">
              <Badge tone={isSupervisor ? 'good' : 'neutral'}>
                {isSupervisor ? 'Supervisor access' : 'Officer access'}
              </Badge>
            </div>
          )}
          <button
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? 'Expand navigation' : 'Collapse navigation'}
            className={cx(
              'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium text-zinc-500 transition-colors hover:bg-zinc-50 hover:text-zinc-800 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-200',
              collapsed && 'justify-center px-0',
            )}
          >
            <MenuIcon className="h-4.5 w-4.5 shrink-0" />
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>
      </nav>

      {/* ---------------- content ---------------- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center gap-3 border-b border-zinc-200 bg-white px-5 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
              {current?.label || 'Console'}
            </h1>
            <p className="truncate text-[11px] text-zinc-500">
              {status?.dataset
                ? `${status.dataset.name} · ${status.companies} companies, ${status.invoices} invoices`
                : 'No dataset loaded'}
            </p>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <DatasetPicker activeId={status?.dataset?.id} onChanged={onRefresh} />
            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
            <span className="mx-1 h-6 w-px bg-zinc-200 dark:bg-zinc-800" />
            <UserMenu />
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
