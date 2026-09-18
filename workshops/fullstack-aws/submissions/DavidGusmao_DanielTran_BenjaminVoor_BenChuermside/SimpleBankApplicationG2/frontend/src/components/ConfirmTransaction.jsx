/* "You are about to..." - the review step before money moves.
 *
 * WCAG 3.3.4 asks that a transaction involving money be reversible, checked, or
 * confirmed. Ours is not reversible - the ledger is append-only and a mistake
 * is corrected by a second entry, not by undoing the first - so it gets
 * confirmed, and this is that step.
 *
 * ABOUT THE "AFTER" FIGURE. It is arithmetic done in the browser, which is the
 * one thing the rest of this app refuses to do with money. It is allowed here
 * and only here because it is a FORECAST of a request not yet sent, not a
 * balance: nothing is read back from it, nothing is stored, and the moment the
 * request returns, the balance shown everywhere is the one the server sent. It
 * is labelled as an estimate on screen so nobody mistakes it for the real one.
 * If two tabs are open it may be wrong, which is exactly why it is not the
 * number anyone is left looking at afterwards.
 */
import { useEffect, useRef } from 'react'
import { formatCents } from '../lib/money'
import { accountLabel, accountTone } from '../lib/accounts'

const WORDING = {
  DEPOSIT: { title: 'Confirm deposit', verb: 'Deposit', direction: 1 },
  WITHDRAW: { title: 'Confirm withdrawal', verb: 'Withdraw', direction: -1 },
  TRANSFER: { title: 'Confirm transfer', verb: 'Send', direction: -1 },
}

export default function ConfirmTransaction({
  open, kind, account, amountCents, recipient, busy, onConfirm, onCancel,
}) {
  const dialogRef = useRef(null)

  /* showModal() traps focus, makes the rest of the page inert and closes on
   * Escape, none of which has to be written here. */
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  if (!kind || !account) return null

  const wording = WORDING[kind]
  const signed = wording.direction * amountCents
  const after = account.balance + signed

  return (
    <dialog ref={dialogRef}
            onCancel={(event) => { event.preventDefault(); onCancel() }}>
      <h2>{wording.title}</h2>

      {/* The account, in its own colour, so you can see at a glance that this
          is the account you meant. */}
      <div className={`confirm-account tone-${accountTone(account)}`}>
        {accountLabel(account)}
      </div>

      <dl className="confirm-rows">
        <div>
          <dt>{wording.verb}</dt>
          {/* The sign is spelled out as well as coloured: red and green alone
              is the most common colour-vision axis (WCAG 1.4.1). */}
          <dd className={signed >= 0 ? 'credit' : 'debit'}>
            {signed >= 0 ? '+' : '−'}{formatCents(amountCents)}
          </dd>
        </div>
        {recipient && (
          <div><dt>To</dt><dd>{recipient}</dd></div>
        )}
        <div><dt>Balance now</dt><dd>{formatCents(account.balance)}</dd></div>
        <div>
          <dt>Balance after</dt>
          <dd>{formatCents(after)}</dd>
        </div>
      </dl>

      <p className="hint">
        {signed >= 0
          ? `This will increase ${accountLabel(account)} by ${formatCents(amountCents)}.`
          : `This will reduce ${accountLabel(account)} by ${formatCents(amountCents)}.`}{' '}
        The balance after is an estimate until the bank confirms it.
      </p>

      <div className="row">
        <button type="button" onClick={onConfirm} disabled={busy}>
          {busy ? 'Sending...' : `Yes, ${wording.verb.toLowerCase()} ${formatCents(amountCents)}`}
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </dialog>
  )
}
