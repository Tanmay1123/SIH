import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { clearToken, getProfile, getToken, logout as apiLogout } from './api'

/**
 * The signed-in account, its role, and what it may do.
 *
 * The permissions map comes from the server (core/roles.py) rather than being
 * inferred in the browser, so there is exactly one definition of who can do
 * what. The UI uses it to avoid showing an action that would only be refused -
 * every one of these is still enforced server-side, because hiding a button is
 * a courtesy, never a control.
 */

const AuthContext = createContext(null)

const NO_PERMISSIONS = {
  can_review: false,
  can_dismiss: false,
  can_confirm: false,
  can_run_detection: false,
  can_upload: false,
  can_issue_report: false,
  can_view_team: false,
  can_edit_settings: false,
  can_manage_datasets: false,
}

export function AuthProvider({ children }) {
  const [profile, setProfile] = useState(null)
  const [checking, setChecking] = useState(true)

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setProfile(null)
      setChecking(false)
      return null
    }
    try {
      const data = await getProfile()
      setProfile(data)
      return data
    } catch {
      clearToken()
      setProfile(null)
      return null
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // A 401 from any call (token expired, revoked, or the account removed) drops
  // us straight back to the login screen.
  useEffect(() => {
    const onUnauthorized = () => setProfile(null)
    window.addEventListener('codenova:unauthorized', onUnauthorized)
    return () => window.removeEventListener('codenova:unauthorized', onUnauthorized)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await apiLogout()
    } catch {
      // The token may already be invalid server-side; clear it locally anyway.
    }
    clearToken()
    setProfile(null)
  }, [])

  const value = useMemo(
    () => ({
      profile,
      checking,
      isAuthenticated: Boolean(profile),
      isSupervisor: profile?.role === 'supervisor',
      can: profile?.permissions || NO_PERMISSIONS,
      refresh,
      setProfile,
      signOut,
    }),
    [profile, checking, refresh, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
