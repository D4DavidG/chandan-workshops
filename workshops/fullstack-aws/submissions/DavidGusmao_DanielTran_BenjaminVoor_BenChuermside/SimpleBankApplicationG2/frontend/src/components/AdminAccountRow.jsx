/* One account in the admin list, with the two things an admin may do to it.
 *
 * Freeze and adjust live in the same component because they share a rule: both
 * need a written reason of at least ten characters, and the backend refuses
 * either without one. Keeping them together means that rule is written once.
 *
 * Note what is deliberately absent: anything that sets a balance. The only way
 * an admin may change one is an adjustment, which posts an ordinary ledger entry
 * tagged with the acting admin and the reason, so balance == sum(ledger) still
 * holds afterwards. A balance moved without a matching entry breaks that
 * permanently, and afterwards there is no way to tell which number was right. */
import { useState } from 'react'
import * as api from '../lib/api'
import { formatCents, parseDollars } from '../lib/money'

const MIN_REASON = 10

export default function AdminAccountRow({ account, onChanged }) {
  const [mode, setMode] = useState(null) // null | 'freeze' | 'adjust'
  const [reason, setReason] = useState('')
  const [amount, setAmount] = useState('')
  const [direction, setDirection] = useState('CREDIT')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const frozen = account.status === 'FROZEN'

  // Opening a panel clears the last one. A reason typed for a freeze must never
  // be submitted with an adjustment.
  function open(next) {
    setMode(next)
    setReason('')
    setAmount('')
    setDirection('CREDIT')
    setError(null)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)

    if (reason.trim().length < MIN_REASON) {
      setError(`Give a reason of at least ${MIN_REASON} characters. It goes in the audit log.`)
      return
    }

    let cents = null
    if (mode === 'adjust') {
      // Zero is rightly refused here - unlike an opening balance, an adjustment
      // of nothing is meaningless - so parseDollars' own rule is what we want.
      cents = parseDollars(amount)
      if (cents === null) {
        setError('Enter an amount like 25.00.')
        return
      }
    }

    setBusy(true)
    try {
      if (mode === 'freeze') await api.adminFreeze(account.accountId, !frozen, reason.trim())
      else await api.adminAdjust(account.accountId, cents, direction, reason.trim())
      setMode(null)
      await onChanged() // the balance, the audit log and the reconciliation all moved
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <p>
        <strong className="admin-account-type">{account.accountType}</strong>{' '}
        #{account.accountId} — {account.userName}{' '}
        <span className="balance">{formatCents(account.balance)}</span>{' '}
        {/* The word, not just the colour: red alone is not a status. */}
        {frozen && <span className="badge">FROZEN</span>}
      </p>
      <p>
        <button type="button" onClick={() => open(mode === 'freeze' ? null : 'freeze')}>
          {frozen ? 'Unfreeze' : 'Freeze'}
        </button>{' '}
        <button type="button" onClick={() => open(mode === 'adjust' ? null : 'adjust')}>
          Adjust
        </button>
      </p>

      {mode && (
        <form onSubmit={handleSubmit}>
          {mode === 'adjust' && (
            <>
              <label>
                Amount
                <input
                  inputMode="decimal"
                  placeholder="25.00"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
              </label>
              <label>
                Direction
                <select value={direction} onChange={(e) => setDirection(e.target.value)}>
                  <option value="CREDIT">Credit — add to the balance</option>
                  <option value="DEBIT">Debit — take off the balance</option>
                </select>
              </label>
            </>
          )}
          <label>
            Reason
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={`at least ${MIN_REASON} characters`}
            />
          </label>
          <p className="hint">
            {mode === 'freeze'
              ? frozen
                ? 'Unfreezing lets the customer move money again.'
                : 'A frozen account refuses every customer-initiated movement. It can still be read, and it can still be adjusted.'
              : 'Posts a ledger entry tagged with your user id and this reason. A debit that would take the balance below zero is refused.'}
          </p>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? 'Working...' : mode === 'freeze' ? (frozen ? 'Unfreeze account' : 'Freeze account') : 'Post adjustment'}
          </button>
        </form>
      )}
    </div>
  )
}
