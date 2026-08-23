import { useEffect, useState } from 'react'
import Dashboard from './Dashboard.jsx'
import Login from './Login.jsx'
import { useTheme } from './useTheme.js'
import { clearToken, getToken, whoami } from './api'

export default function App() {
  // Applied at the top of the tree (not inside Dashboard) so the chosen
  // theme is already in effect on the login screen, before there's a
  // Dashboard to render at all.
  const { theme, toggle: toggleTheme } = useTheme()

  // null = still checking a stored token, undefined-ish states handled below
  const [username, setUsername] = useState(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    const token = getToken()
    if (!token) {
      setChecking(false)
      return
    }
    whoami()
      .then((data) => setUsername(data.username))
      .catch(() => clearToken())
      .finally(() => setChecking(false))
  }, [])

  // A 401 from any API call (token expired, revoked, or never valid) drops us
  // straight back to the login screen.
  useEffect(() => {
    const onUnauthorized = () => setUsername(null)
    window.addEventListener('codenova:unauthorized', onUnauthorized)
    return () => window.removeEventListener('codenova:unauthorized', onUnauthorized)
  }, [])

  if (checking) {
    return <div className="flex h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950" />
  }

  if (!username) {
    return <Login onAuthenticated={setUsername} />
  }

  return (
    <Dashboard
      username={username}
      onLoggedOut={() => setUsername(null)}
      theme={theme}
      onToggleTheme={toggleTheme}
    />
  )
}
