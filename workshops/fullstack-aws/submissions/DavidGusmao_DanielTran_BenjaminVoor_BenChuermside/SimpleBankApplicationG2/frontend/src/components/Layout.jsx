/* The frame every page renders inside: nav bar at the top, page below. */
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useAuth } from '../context/auth-context'
import { activeTheme, applyTheme } from '../lib/theme'

export default function Layout() {
  const { user, accounts, logout, isAdmin } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  /* Red bar whenever anything admin is going on: you are signed in as an admin,
   * or you are standing on a staff page. `.theme-admin` redefines --navy, and
   * the bar is painted with --navy, so nothing below has to know about this. */
  const adminContext = isAdmin || location.pathname.startsWith('/admin')
  const hasAccounts = accounts.length > 0

  // Read once on mount: after that this component owns the value, and the only
  // thing that changes it is the button below.
  const [theme, setTheme] = useState(activeTheme)

  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }

  function handleLogout() {
    logout()
    navigate('/')
  }

  return (
    <div className="app">
      <header className={adminContext ? 'nav theme-admin' : 'nav'}>
        {/* The bar spans the window; this keeps its contents on the same rail as
            the page below, so the brand is not stuck to the window edge. */}
        <div className="nav-inner">
        <Link to="/" className="nav-brand">Simple Bank</Link>

        {/* Home always. Then the money pages, but only once there is an
            account behind them - offering Deposit to somebody with nothing to
            deposit into is a link to a dead end. With no account there is
            exactly one thing to do, so that is the only thing offered.

            An admin holds no accounts and makes no transfers. The backend
            refuses both regardless; this is just not offering what it would
            refuse. */}
        <nav className="nav-links">
          <NavLink to="/" end>Home</NavLink>
          {!isAdmin && (hasAccounts ? (
            <>
              <NavLink to="/accounts">Accounts</NavLink>
              <NavLink to="/deposit">Deposit</NavLink>
              <NavLink to="/withdraw">Withdraw</NavLink>
              <NavLink to="/transfer">Transfer</NavLink>
              {/* Last: the three before it are things you do, this is the
                  record of having done them. */}
              <NavLink to="/history">History</NavLink>
            </>
          ) : (
            user && <NavLink to="/accounts/new">Open an account</NavLink>
          ))}
          {isAdmin && <NavLink to="/admin">Admin</NavLink>}
        </nav>

        <div className="nav-user">
          {/* Says what pressing it does, not what the page currently is - a
              button labelled "Dark" while the page is already dark is the
              commonest way to get this wrong. */}
          <button type="button" className="theme-toggle" onClick={toggleTheme}
                  aria-pressed={theme === 'dark'}>
            {theme === 'dark' ? 'Light mode' : 'Dark mode'}
          </button>
          {user ? (
            <>
              {/* The name is the way into the profile - the usual place to look. */}
              <NavLink to="/profile" className="nav-name">
                {user.name}
                {isAdmin && <span className="nav-role">ADMIN</span>}
              </NavLink>
              <button onClick={handleLogout}>Log out</button>
            </>
          ) : (
            <>
              <NavLink to="/register">Register</NavLink>
              <NavLink to="/login">Sign in</NavLink>
            </>
          )}
        </div>
        </div>
      </header>

      <main className="page">
        <Outlet />
      </main>
    </div>
  )
}
