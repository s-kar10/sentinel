import { useEffect, useState } from 'react'
import {
  ExternalLink,
  LayoutDashboard,
  Menu,
  Plus,
  Radar,
  ServerCog,
  ShieldCheck,
  X,
} from 'lucide-react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { api, API_URL } from '../lib/api'

const navigation = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/targets', label: 'Targets', icon: ServerCog, end: false },
  { to: '/evaluations', label: 'Evaluations', icon: Radar, end: false },
]

export function AppShell() {
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [apiHealthy, setApiHealthy] = useState<boolean | null>(null)

  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    let active = true
    api
      .health()
      .then(() => active && setApiHealthy(true))
      .catch(() => active && setApiHealthy(false))
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      <header className="mobile-header">
        <Link className="brand" to="/" aria-label="Sentinel home">
          <span className="brand__mark" aria-hidden="true">
            <ShieldCheck size={20} strokeWidth={2.25} />
          </span>
          <span>Sentinel</span>
        </Link>
        <button
          type="button"
          className="icon-button icon-button--dark"
          aria-expanded={menuOpen}
          aria-controls="primary-navigation"
          aria-label={menuOpen ? 'Close navigation' : 'Open navigation'}
          onClick={() => setMenuOpen((value) => !value)}
        >
          {menuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </header>

      {menuOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}

      <aside className={`sidebar ${menuOpen ? 'sidebar--open' : ''}`}>
        <div>
          <Link className="brand sidebar__brand" to="/" aria-label="Sentinel home">
            <span className="brand__mark" aria-hidden="true">
              <ShieldCheck size={21} strokeWidth={2.25} />
            </span>
            <span>Sentinel</span>
          </Link>
          <p className="sidebar__label">Security workspace</p>
          <nav id="primary-navigation" className="sidebar__nav" aria-label="Primary navigation">
            {navigation.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => `nav-link ${isActive ? 'nav-link--active' : ''}`}
              >
                <Icon size={18} aria-hidden="true" />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="sidebar__footer">
          <Link to="/targets/new" className="button button--sidebar">
            <Plus size={17} aria-hidden="true" />
            Register target
          </Link>
          <div className="api-indicator" title={API_URL}>
            <span
              className={`api-indicator__dot ${
                apiHealthy === true ? 'is-online' : apiHealthy === false ? 'is-offline' : ''
              }`}
              aria-hidden="true"
            />
            <span>{apiHealthy === true ? 'API connected' : apiHealthy === false ? 'API unavailable' : 'Checking API'}</span>
            <ExternalLink size={13} aria-hidden="true" />
          </div>
        </div>
      </aside>

      <main id="main-content" className="main-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  )
}
