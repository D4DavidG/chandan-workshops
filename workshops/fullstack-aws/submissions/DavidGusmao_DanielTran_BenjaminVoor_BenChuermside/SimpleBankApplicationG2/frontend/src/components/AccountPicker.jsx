/* "Which account?" - the first question on Deposit, Withdraw and History.
 *
 * The whole thing sits in a bubble painted in the selected account's colour, so
 * which account you are about to act on is visible without reading. That is the
 * point: the most expensive mistake on these pages is doing the right thing to
 * the wrong account.
 *
 * With one account there is no question, so it is not asked - it renders as a
 * plain label rather than a dropdown that cannot be changed.
 */
import { accountLabel, accountTone } from '../lib/accounts'
import { formatCents } from '../lib/money'

export default function AccountPicker({ accounts, value, onChange, label = 'Account' }) {
  const current = accounts.find((a) => a.accountId === Number(value)) ?? accounts[0]
  if (!current) return null

  return (
    <div className={`account-bubble tone-${accountTone(current)}`}>
      {accounts.length === 1 ? (
        <div className="bubble-single">
          <strong>{accountLabel(current)}</strong>
          <span className="bubble-balance">{formatCents(current.balance)}</span>
        </div>
      ) : (
        <label className="bubble-label">
          {label}
          <select value={current.accountId} onChange={(e) => onChange(Number(e.target.value))}>
            {accounts.map((a) => (
              <option key={a.accountId} value={a.accountId}>
                {accountLabel(a)} — {formatCents(a.balance)}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  )
}
