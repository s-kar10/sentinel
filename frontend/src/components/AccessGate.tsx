import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { api } from '../lib/api'
import { ACCESS_ENDED, endAccess, setAccessToken } from '../lib/access'
import { ErrorState, PageLoader } from './AsyncState'

export function AccessGate({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<'local' | 'token' | null>(null)
  const [identity, setIdentity] = useState<{ name: string; role: string; project_name: string; organization_name: string } | null>(null)
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [loadingError, setLoadingError] = useState('')
  const [busy, setBusy] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    api.accessStatus().then((result) => {
      if (!['local', 'token'].includes(result.mode)) throw new Error('Unknown access mode.')
      if (active) { setMode(result.mode); setLoadingError('') }
    }).catch(() => { if (active) setLoadingError('Unable to verify API access settings.') })
    return () => { active = false }
  }, [attempt])

  useEffect(() => {
    const clear = () => {
      setIdentity(null)
      setValue('')
    }
    window.addEventListener(ACCESS_ENDED, clear)
    return () => { window.removeEventListener(ACCESS_ENDED, clear); setAccessToken('') }
  }, [])

  async function signIn(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setAccessToken(value.trim())
    setValue('')
    try {
      setIdentity(await api.accessIdentity())
    } catch {
      setAccessToken('')
      setError('Sign-in failed. Check the token, its expiry, and API availability.')
    } finally { setBusy(false) }
  }

  if (loadingError) return <div className="page"><ErrorState title="Access settings unavailable" message={loadingError} onRetry={() => setAttempt((n) => n + 1)} /></div>
  if (!mode) return <div className="page"><PageLoader label="Checking access" /></div>
  if (mode === 'local') return children
  if (!identity) return <main className="page">
    <section className="panel access-panel">
      <h1>Sign in to Sentinel</h1>
      <p>Enter an operator-issued access token. It stays in this tab’s memory and is cleared on reload or sign-out.</p>
      <form onSubmit={(event) => void signIn(event)}>
        <label>Access token<input type="password" autoComplete="off" value={value} maxLength={100} disabled={busy} onChange={(event) => setValue(event.target.value)} /></label>
        {error && <p role="alert">{error}</p>}
        <button className="button button--primary" disabled={busy || !value.trim()}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </section>
  </main>
  return <>
    <div className="access-banner" role="region" aria-label="Current access">
      <span>{identity.name} · {identity.role} · {identity.organization_name} / {identity.project_name}</span>
      <button type="button" className="button button--secondary button--small" onClick={() => endAccess()}>Sign out</button>
    </div>
    {children}
  </>
}
