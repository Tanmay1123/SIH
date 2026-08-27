/**
 * Where the API lives.
 *
 * Vite inlines `import.meta.env.*` at BUILD time, not at runtime - so on
 * Vercel, VITE_API_BASE_URL has to exist as a project environment variable
 * before the build runs. Setting it afterwards changes nothing until the next
 * deploy, which is a genuinely confusing failure the first time you hit it.
 *
 * Worse, the localhost fallback below is a perfectly reasonable default for
 * development and a silent disaster in production: the deployed page is served
 * over HTTPS, so a browser refuses the http://localhost:8000 request as mixed
 * content and reports it as a generic network error with nothing pointing at
 * the real cause. So we say the real cause out loud, once, at startup.
 */

const FALLBACK = 'http://localhost:8000/api'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || FALLBACK

/** True when we are clearly deployed rather than running on a dev machine. */
function looksDeployed() {
  if (typeof window === 'undefined') return false
  const { hostname } = window.location
  return hostname !== 'localhost' && hostname !== '127.0.0.1' && hostname !== '[::1]'
}

if (API_BASE_URL === FALLBACK && looksDeployed()) {
  // eslint-disable-next-line no-console
  console.error(
    [
      'CodeNova: VITE_API_BASE_URL is not set, so this build is pointing at',
      `${FALLBACK} - a machine that does not exist from here. Every API call`,
      'will fail.',
      '',
      'Fix: set VITE_API_BASE_URL to the backend URL in your hosting project',
      'settings, then REDEPLOY. Vite bakes this value into the bundle at build',
      'time, so an existing deployment will not pick it up on its own.',
    ].join('\n'),
  )
}
