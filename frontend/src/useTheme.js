import { useEffect, useState } from 'react'

const STORAGE_KEY = 'codenova_theme'

function applyTheme(theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

/**
 * Dark by default (this app was designed dark-first), toggleable to light,
 * remembered across visits.
 */
export function useTheme() {
  const [theme, setTheme] = useState(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'dark'
  })

  useEffect(() => {
    applyTheme(theme)
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const toggle = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))

  return { theme, toggle }
}
