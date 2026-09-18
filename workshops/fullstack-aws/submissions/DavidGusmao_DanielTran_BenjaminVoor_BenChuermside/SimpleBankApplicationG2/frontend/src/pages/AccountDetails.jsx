import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import * as api from '../lib/api'
import { formatCents } from '../lib/money'
import { accountLabel, accountTone } from '../lib/accounts'

export default function AccountDetails() {
  const { accountId } = useParams()
  const [account, setAccount] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!accountId) return

    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)

      try {
        const { account } = await api.getAccount(Number(accountId))
        if (!cancelled) setAccount(account)
      } catch (err) {
        if (!cancelled) setError(err?.message || 'Unable to load this account.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [accountId])

  if (loading) {
    return (
      <div className="card">
        <h1>Account details</h1>
        <p className="hint">Loading account...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="card">
        <h1>Account details</h1>
        <p className="error">{error}</p>
      </div>
    )
  }

  if (!account) {
    return (
      <div className="card">
        <h1>Account details</h1>
        <p>No account found.</p>
      </div>
    )
  }

  /* The whole card wears the account's colour, not a stripe of it: this is the
   * page about that one account, so the colour is the subject rather than a
   * label on it. The rows inside stay white, because dark text on a saturated
   * fill is the one thing these colours cannot carry - see index.css. */
  const tone = accountTone(account)

  return (
    <div className={`card account-card tone-${tone}`}>
      <div className="account-card-head">
        <h1>{accountLabel(account)} account</h1>
        {account.status === 'FROZEN' && <span className="badge">FROZEN</span>}
        <span className="account-card-balance">{formatCents(account.balance)}</span>
      </div>

      <dl className="detail-rows">
        <div><dt>Owner</dt><dd>{account.userName ?? 'Unknown owner'}</dd></div>
        <div><dt>Balance</dt><dd>{formatCents(account.balance)}</dd></div>
        <div><dt>Type</dt><dd>{account.accountType}</dd></div>
        <div>
          <dt>Available to withdraw</dt>
          <dd>{formatCents(account.availableForWithdrawal)}</dd>
        </div>
        <div><dt>Status</dt><dd>{account.status}</dd></div>
      </dl>

      {/* Same order as the nav bar: Deposit, Withdraw, Transfer, History.
          Two different orders for the same four things is a small thing that
          makes people read the row every time instead of reaching for it. */}
      <div className="actions">
        <Link className="action lift" to={`/accounts/${account.accountId}/deposit`}>Deposit</Link>
        <Link className="action lift" to={`/accounts/${account.accountId}/withdraw`}>Withdraw</Link>
        <Link className="action lift" to="/transfer">Transfer</Link>
        <Link className="action lift" to={`/accounts/${account.accountId}/transactions`}>History</Link>
      </div>
    </div>
  )
}
