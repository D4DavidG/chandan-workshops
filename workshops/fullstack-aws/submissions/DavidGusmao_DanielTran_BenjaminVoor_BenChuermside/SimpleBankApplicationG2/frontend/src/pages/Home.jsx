/* The home page, and the first thing anyone sees.
 *
 * It is public, so it has to be two pages in one: a landing page with the
 * sign-in form for a visitor, the account summary for somebody already signed
 * in. That is one `if`, and it is the reason every other route can stay behind
 * the auth guard - this is the only door.
 *
 * The offer shows either way. The only thing signing in removes is the sign-in
 * form beside it.
 */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import * as api from '../lib/api'
import { useAuth } from '../context/auth-context'
import { formatCents } from '../lib/money'
import { accountLabel, accountTone } from '../lib/accounts'
import LoginForm from '../components/LoginForm'
import AboutUs from '../components/AboutUs'
import AdminAuditLog from '../components/AdminAuditLog'

/* A spanner. Inline rather than an emoji so it matches the button's text
 * colour and looks the same on every platform. */
function WrenchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14.7 6.3a4 4 0 0 0 5 5l-9.4 9.4a2.1 2.1 0 0 1-3-3l9.4-9.4Z" />
      <path d="M19.7 11.3 22 9a5.5 5.5 0 0 0-7-7l2.3 2.3a2 2 0 0 1 0 2.8l-1.2 1.2a2 2 0 0 0 0 2.8Z" />
    </svg>
  )
}

function Promo({ signedIn = false }) {
  return (
    <div className="promo card lift">
      <h2>Start our new credit card with 10% APR!</h2>
      <div className="promo-inner card">
        <p>Start a new account at Simple Bank!</p>
        <p>Representative APR 10%. Credit is subject to status.</p>
        {/* Signed in, this opens the credit account the offer is about.
            Signed out, it has to make you an account first. */}
        <Link className="apply lift" to={signedIn ? '/accounts/new?type=CREDIT' : '/register'}>
          Apply now
        </Link>
      </div>
    </div>
  )
}

/* One bar per account, each a different colour. The colour is picked by
 * accountId rather than by position in the list, so an account keeps the same
 * colour after one above it is closed or the order changes - a balance that
 * changes colour between visits is a balance you look at twice. */
function AccountBars({ accounts }) {
  return (
    <ul className="bars">
      {accounts.map((account) => (
        <li key={account.accountId}>
          <Link to={`/accounts/${account.accountId}`}
                className={`bar lift bar-${accountTone(account)}`}>
            <span className="bar-type">{accountLabel(account)}</span>
            {account.status === 'FROZEN' && <span className="badge">FROZEN</span>}
            {/* Divide by 100 to display, never to calculate. */}
            <span className="bar-balance">{formatCents(account.balance)}</span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

function Landing() {
  const navigate = useNavigate()
  return (
    <>
      <div className="hero">
        <Promo />
        <div className="signin card">
          <LoginForm onDone={() => navigate('/')} />
        </div>
      </div>
      <AboutUs />
    </>
  )
}

function Dashboard() {
  const { user, accounts, isAdmin } = useAuth()
  const [auditEntries, setAuditEntries] = useState([])

  useEffect(() => {
    if (!isAdmin) return
    // A customer would get a 403 here, which is why it is behind the role check
    // rather than being fetched for everybody and thrown away.
    api.adminAudit()
      .then((data) => setAuditEntries(data.entries ?? data.audit ?? []))
      .catch(() => setAuditEntries([]))
  }, [isAdmin])

  return (
    <div>
      {/* Staff red for an admin, ordinary brand ink for a customer. This page
          is outside .theme-admin, so it does not pick the red up on its own. */}
      <h1 className={isAdmin ? 'staff-heading' : undefined}>Welcome back, {user.name}</h1>

      {/* Same offer as the landing page, without the sign-in form beside it.
          Not shown to an admin: it is a customer acquisition offer, and an
          admin cannot open the account it is offering. */}
      {!isAdmin && (
        <div className="hero hero-solo">
          <Promo signedIn />
        </div>
      )}

      {/* An admin holds no accounts by design, so everything the customer
          dashboard offers is about something they do not have. One way in,
          and the record of what staff have done underneath it. */}
      {isAdmin ? (
        <>
          <Link className="admin-cta lift" to="/admin">
            <WrenchIcon />
            Admin tools
          </Link>
          <h2 className="audit-heading">Recent activity</h2>
          <AdminAuditLog entries={auditEntries} />
        </>
      ) : (
        <>
          {accounts.length > 0
            ? <AccountBars accounts={accounts} />
            : <div className="card"><p>You do not have a bank account yet.</p></div>}

          <div className="actions">
            <Link className="action lift" to="/accounts/new">Open an account</Link>
            {accounts.length > 0 && <Link className="action lift" to="/transfer">Transfer money</Link>}
            <Link className="action lift" to="/profile">My details</Link>
          </div>
        </>
      )}

      {/* Not on a staff dashboard: it is a public-facing panel, and its navy
          button sits badly on the red admin theme. */}
      {!isAdmin && <AboutUs />}
    </div>
  )
}

export default function Home() {
  const { user } = useAuth()
  return user ? <Dashboard /> : <Landing />
}
