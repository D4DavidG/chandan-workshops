import { useParams } from 'react-router-dom'
/* Brief 7.4. Pick an account, put money in.
 *
 * The form itself is TransactionMenu pinned to one action, so deposit, withdraw
 * and transfer keep sharing the amount parsing, the idempotency id and the
 * "render the balance the server returned" rule rather than each re-deriving
 * them. This page only answers "which account". */
import { useState } from 'react'
import { useAuth } from '../context/auth-context'
import AccountPicker from '../components/AccountPicker'
import TransactionMenu from './TransactionMenu'
import NoAccountsYet from '../components/NoAccountsYet'

export default function Deposit() {
  const { accounts, refreshAccounts } = useAuth()
  /* The account from the URL when there is one - /accounts/25/withdraw means
   * that account, and starting on a different one is how you withdraw from the
   * wrong place. Falls back to the first account for the bare /withdraw route. */
  const { accountId } = useParams()
  const [id, setId] = useState(Number(accountId) || accounts[0]?.accountId || '')
  const account = accounts.find((a) => a.accountId === Number(id))

  if (accounts.length === 0) return <NoAccountsYet action="deposit into" />

  return (
    <div className="card profile">
      <h1>Deposit</h1>
      <AccountPicker accounts={accounts} value={id} onChange={setId} label="Deposit into" />
      {/* The nav and the home page read the account list, so a balance that
          just moved has to be refetched or both keep showing the old one. */}
      <TransactionMenu account={account} fixedKind="DEPOSIT"
                       onAccountChange={() => refreshAccounts()} />
    </div>
  )
}
