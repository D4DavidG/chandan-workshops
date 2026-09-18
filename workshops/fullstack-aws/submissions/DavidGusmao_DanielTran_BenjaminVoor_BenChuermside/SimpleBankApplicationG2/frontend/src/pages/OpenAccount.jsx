/* Brief 7.2 (the bank-account half). Registering a user and opening an account
 * for them are two different things in this API; Register.jsx does the first and
 * sends you here for the second.
 *
 * There is no owner field on this form. The backend takes the owner from the
 * token rather than the body, so a user cannot open an account in somebody
 * else's name - see the note in bank/api.py's create_account. An admin opening
 * one on a customer's behalf passes userId, and that belongs on the admin page,
 * not on this form. */
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/auth-context'
import * as api from '../lib/api'
import { parseDollars } from '../lib/money'

/* parseDollars() answers null for two different situations: text that is not a
 * usable amount, and an amount of zero. That is right for a deposit, where zero
 * is meaningless, and wrong here, where opening an account with nothing in it is
 * the ordinary case. So this tells the two apart rather than refusing "0", and
 * money.js is left alone - it is a shared file and Deposit and Withdraw need it
 * to keep rejecting zero.
 *
 * The regex below is parseDollars' own rule: a whole number of dollars, or
 * dollars and exactly two decimal places. It has to stay in step with it, so
 * "0.0" is refused here for the same reason "1.1" is refused there - one digit
 * after the point is as likely to be unfinished typing as it is to be a tenth.
 *
 * Returns cents, or null when the text is genuinely unusable. */
function parseOpeningBalance(text) {
  const trimmed = text.trim()
  if (trimmed === '') return 0
  const cents = parseDollars(trimmed)
  if (cents !== null) return cents
  return /^\d+(\.\d{2})?$/.test(trimmed.replace(/[$,\s]/g, '')) ? 0 : null
}

export default function OpenAccount() {
  const navigate = useNavigate()
  const { refreshAccounts } = useAuth()
  /* The credit card offer on the home page links here with ?type=CREDIT, so
   * "Apply now" lands on this form with the right product already chosen
   * rather than on a page where you have to find it again. */
  const [searchParams] = useSearchParams()
  const requested = (searchParams.get('type') || '').toUpperCase()
  const [accountType, setAccountType] = useState(
    ['CHECKING', 'SAVINGS', 'CREDIT'].includes(requested) ? requested : 'CHECKING',
  )
  const [openingBalance, setOpeningBalance] = useState('')
  const [amountError, setAmountError] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)
    setAmountError(null)

    // Validate before sending. The backend refuses a bad amount anyway, but a
    // message beside the field beats a banner at the top of the page.
    const cents = parseOpeningBalance(openingBalance)
    if (cents === null) {
      setAmountError('Enter an amount like 250 or 250.00, or leave this empty.')
      return
    }

    setBusy(true)
    try {
      const { account } = await api.openAccount(accountType, cents)
      // PLAN section 3 names deposit, withdraw and transfer, but this changes the
      // same shared list: the nav bar counts it and switches between the
      // "Accounts (n)" tab and "Open account" depending on how many there are.
      await refreshAccounts()
      navigate(`/accounts/${account.accountId}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card narrow">
      <h1>Open account</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Account type
          <select value={accountType} onChange={(e) => setAccountType(e.target.value)}>
            <option value="CHECKING">Checking</option>
            <option value="SAVINGS">Savings</option>
            <option value="CREDIT">Credit card</option>
          </select>
        </label>

        <label>
          Opening balance
          <input
            inputMode="decimal"
            placeholder="0.00"
            value={openingBalance}
            onChange={(e) => setOpeningBalance(e.target.value)}
            aria-invalid={amountError ? 'true' : undefined}
            aria-describedby={amountError ? 'opening-balance-error' : 'opening-balance-hint'}
          />
        </label>
        {amountError ? (
          // Tied to the field rather than signalled by a border colour, so a
          // screen reader reads the reason and not just "invalid".
          <p className="error" id="opening-balance-error">{amountError}</p>
        ) : (
          <p className="hint" id="opening-balance-hint">
            Optional. Leave it empty to open the account with nothing in it. Any
            amount you put here is posted as a real DEPOSIT, so the ledger still
            adds up to the balance.
          </p>
        )}

        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? 'Opening...' : 'Open account'}</button>
      </form>
    </div>
  )
}
