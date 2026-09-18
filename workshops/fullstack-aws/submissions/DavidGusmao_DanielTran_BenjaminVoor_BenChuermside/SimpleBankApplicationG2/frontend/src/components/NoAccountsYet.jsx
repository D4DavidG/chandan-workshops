/* What Deposit, Withdraw and History show when there is nothing to act on.
 *
 * The nav does not offer these pages without an account, so arriving here means
 * a typed URL or a bookmark. Worth answering properly rather than with a blank
 * page. */
import { Link } from 'react-router-dom'

export default function NoAccountsYet({ action }) {
  return (
    <div className="card narrow">
      <h1>No accounts yet</h1>
      <p>You need an account before you can {action} one.</p>
      <Link className="apply lift" to="/accounts/new">Open an account</Link>
    </div>
  )
}
