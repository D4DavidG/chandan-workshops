/* The account list. Same coloured bars as the home page, so an account looks
 * the same wherever you meet it.
 *
 * The accounts come from the auth context rather than a fetch here, because the
 * nav needs the same list to decide what to offer. */
import { Link } from 'react-router-dom'
import { useAuth } from '../context/auth-context'
import { formatCents } from '../lib/money'
import { accountLabel, accountTone } from '../lib/accounts'

export default function Accounts() {
  const { accounts } = useAuth()

  if (accounts.length === 0) {
    return (
      <div className="card narrow">
        <h1>Your accounts</h1>
        <p>Nothing here yet.</p>
        <Link className="apply lift" to="/accounts/new">Open an account</Link>
      </div>
    )
  }

  return (
    <div>
      <div className="section-head">
        <h1>Your accounts</h1>
        {/* At the top, and a button: it is the one thing you come here to do
            that is not just reading. At the bottom it was below the fold as
            soon as somebody had four accounts. */}
        <Link className="apply lift open-another" to="/accounts/new">
          Open another account
        </Link>
      </div>

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
    </div>
  )
}
