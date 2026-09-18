/* Brief 7.6. Pick an account, read its ledger.
 *
 * Same shape as Deposit and Withdraw on purpose: the page holds the card, the
 * title and the account picker, and the inner component holds the thing you
 * came for. That is why these four pages look like one another.
 *
 * Serves both /history and /accounts/:accountId/transactions - the second just
 * arrives with the account already chosen.
 */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../context/auth-context'
import AccountPicker from '../components/AccountPicker'
import Transactions from './Transactions'
import NoAccountsYet from '../components/NoAccountsYet'

export default function History() {
  const { accounts } = useAuth()
  /* The account from the URL when there is one. /accounts/25/transactions means
   * that account; the bare /history route starts on the first. */
  const { accountId } = useParams()
  const [id, setId] = useState(Number(accountId) || accounts[0]?.accountId || '')

  if (accounts.length === 0) return <NoAccountsYet action="see the history of" />

  return (
    <div className="card profile">
      <h1>History</h1>
      <AccountPicker accounts={accounts} value={id} onChange={setId} label="History for" />
      {/* `key` on the account id: changing account remounts the table, which
          resets its page number for free. */}
      <Transactions key={id} accountId={id} />
    </div>
  )
}
