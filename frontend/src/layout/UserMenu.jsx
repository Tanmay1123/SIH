import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../useAuth.jsx'
import { Avatar, Badge, cx } from '../components/ui.jsx'
import { ChevronDownIcon, LogoutIcon, SettingsIcon, ShieldIcon, UserIcon } from '../icons.jsx'

/**
 * The account control in the top bar.
 *
 * One button carrying who you are, opening onto who you are in more detail,
 * your role, and the way out. Previously the only account affordance was a
 * bare "Log out" link sitting next to a username, which told you nothing and
 * offered nowhere to go.
 */
export default function UserMenu() {
  const { profile, isSupervisor, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const boxRef = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!profile) return null

  const go = (path) => {
    setOpen(false)
    navigate(path)
  }

  return (
    <div className="relative" ref={boxRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cx(
          'flex items-center gap-2 rounded-full py-1 pl-1 pr-2.5 transition-colors',
          open
            ? 'bg-zinc-100 dark:bg-zinc-800'
            : 'hover:bg-zinc-100 dark:hover:bg-zinc-800',
        )}
      >
        <Avatar name={profile.full_name} size="md" />
        <span className="hidden text-left sm:block">
          <span className="block max-w-[9rem] truncate text-xs font-medium leading-tight text-zinc-800 dark:text-zinc-200">
            {profile.full_name}
          </span>
          <span className="block text-[10px] leading-tight text-zinc-500">
            {profile.role_label}
          </span>
        </span>
        <ChevronDownIcon
          className={cx(
            'h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-72 overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="flex items-start gap-3 border-b border-zinc-200 px-4 py-3.5 dark:border-zinc-800">
            <Avatar name={profile.full_name} size="lg" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                {profile.full_name}
              </p>
              <p className="truncate text-xs text-zinc-500">@{profile.username}</p>
              <p className="mt-0.5 truncate text-xs text-zinc-500">
                {profile.email || (
                  <span className="text-amber-600 dark:text-amber-400">No email set</span>
                )}
              </p>
              <Badge tone={isSupervisor ? 'good' : 'neutral'} className="mt-2">
                {isSupervisor && <ShieldIcon className="h-2.5 w-2.5" />}
                {profile.role_label}
              </Badge>
            </div>
          </div>

          <div className="px-4 py-3 text-[11px] leading-relaxed text-zinc-500">
            {isSupervisor
              ? 'You can confirm alerts as fraudulent, see every officer’s activity, and change detection policy.'
              : 'You can review, clear alerts and issue reports. Confirming an alert as fraudulent is a supervisor’s decision.'}
          </div>

          <div className="border-t border-zinc-200 p-1.5 dark:border-zinc-800">
            <MenuItem icon={<UserIcon className="h-4 w-4" />} onClick={() => go('/profile')}>
              Your profile
            </MenuItem>
            <MenuItem icon={<SettingsIcon className="h-4 w-4" />} onClick={() => go('/settings')}>
              {isSupervisor ? 'Detection settings' : 'View settings'}
            </MenuItem>
            {!profile.email && (
              <Link
                to="/profile"
                onClick={() => setOpen(false)}
                className="mx-1 mb-1 block rounded-lg bg-amber-50 px-2.5 py-2 text-[11px] leading-relaxed text-amber-800 dark:bg-amber-950/50 dark:text-amber-200"
              >
                Add an email address so your copy of each case report reaches you.
              </Link>
            )}
          </div>

          <div className="border-t border-zinc-200 p-1.5 dark:border-zinc-800">
            <MenuItem
              icon={<LogoutIcon className="h-4 w-4" />}
              onClick={() => {
                setOpen(false)
                signOut()
              }}
              tone="danger"
            >
              Sign out
            </MenuItem>
          </div>
        </div>
      )}
    </div>
  )
}

function MenuItem({ icon, children, onClick, tone = 'default' }) {
  return (
    <button
      role="menuitem"
      onClick={onClick}
      className={cx(
        'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs font-medium transition-colors',
        tone === 'danger'
          ? 'text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/50'
          : 'text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800',
      )}
    >
      <span className="shrink-0 text-zinc-400">{icon}</span>
      {children}
    </button>
  )
}
