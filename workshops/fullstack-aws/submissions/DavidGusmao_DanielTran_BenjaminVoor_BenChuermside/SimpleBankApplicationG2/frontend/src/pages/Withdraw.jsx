import { useParams } from 'react-router-dom'
/* Brief 7.5. The mirror of Deposit - see that file for why the form is shared. */
import { useState } from 'react'
import { useAuth } from '../context/auth-context'
import AccountPicker from '../components/AccountPicker'
import TransactionMenu from './TransactionMenu'
import NoAccountsYet from '../components/NoAccountsYet'

export default function Withdraw() {
  const { accounts, refreshAccounts } = useAuth()
  /* The account from the URL when there is one - /accounts/25/withdraw means
   * that account, and starting on a different one is how you withdraw from the
   * wrong place. Falls back to the first account for the bare /withdraw route. */
  const { accountId } = useParams()
  const [id, setId] = useState(Number(accountId) || accounts[0]?.accountId || '')
  const account = accounts.find((a) => a.accountId === Number(id))

  if (accounts.length === 0) return <NoAccountsYet action="withdraw from" />

  return (
    <div className="card profile">
      <h1>Withdraw</h1>
      <AccountPicker accounts={accounts} value={id} onChange={setId} label="Withdraw from" />
      <TransactionMenu account={account} fixedKind="WITHDRAW"
                       onAccountChange={() => refreshAccounts()} />
    </div>
  )
}
