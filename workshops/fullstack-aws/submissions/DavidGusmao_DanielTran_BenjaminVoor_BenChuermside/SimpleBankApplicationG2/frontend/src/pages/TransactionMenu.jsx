/* The "move money" screen: pick an action, fill in the form, submit.
 *
 * The account comes in as a prop - this page never fetches it. Everything on
 * screen below the picker is decided by one piece of state, `kind`, so there is
 * one form here, not three.
 *
 * Note: this is NOT src/pages/Transactions.jsx. That one is the history table
 * for a single account (brief 7.6).
 */
import { useState } from 'react'
import * as api from '../lib/api'
import { formatCents, parseDollars } from '../lib/money'
import { accountLabel } from '../lib/accounts'
import ConfirmTransaction from '../components/ConfirmTransaction'

/* The three actions, as data rather than as three copies of the same JSX.
 *
 * Deposit, withdraw and transfer differ in four ways: what the dropdown calls
 * them, what the amount field is labelled, what the button says, and which API
 * function they end up calling. Transfer needs one extra field. That is the
 * whole difference - so it is written down once here, and the component below
 * renders whichever entry is selected.
 *
 * Adding a fourth action later means adding an entry to this object. It means
 * no new JSX and no new branch, which is the point: a `switch` with three
 * nearly-identical arms is the thing this avoids.
 *
 * `send` takes the same four arguments in every entry even though deposit and
 * withdraw ignore `toAccountId`. A uniform signature is what lets the submit
 * handler call `kindConfig.send(...)` without knowing which one it has.
 */
const KINDS = {
  DEPOSIT: {
    label: 'Deposit',
    amountLabel: 'Deposit amount',
    submitLabel: 'Submit deposit',
    needsDestination: false,
    send: (account, cents, toAccountId, clientTxnId) =>
      api.deposit(account.accountId, cents, clientTxnId),
  },
  WITHDRAW: {
    label: 'Withdraw',
    amountLabel: 'Withdrawal amount',
    submitLabel: 'Submit withdrawal',
    needsDestination: false,
    send: (account, cents, toAccountId, clientTxnId) =>
      api.withdraw(account.accountId, cents, clientTxnId),
  },
  TRANSFER: {
    label: 'Transfer',
    amountLabel: 'Transfer amount',
    submitLabel: 'Submit transfer',
    needsDestination: true,
    send: (account, cents, toAccountId, clientTxnId) =>
      api.transfer(account.accountId, toAccountId, cents, clientTxnId),
  },
}

/* `onAccountChange` is optional. Every one of these endpoints answers with the
 * account as it stands afterwards, and the caller owns the account, so the new
 * one is handed back up rather than patched in here. A component never writes
 * to its own props.
 *
 * `?.()` below means "call it only if it was passed", so a caller that does not
 * care can leave it off. */
/* `fixedKind` pins this to one action and hides the picker, which is what the
 * dedicated Deposit and Withdraw pages want - the page title has already said
 * which one it is, so a dropdown offering to change it is a second answer to a
 * question nobody asked. Left off, the picker behaves as before. */
export default function TransactionMenu({ account, onAccountChange, fixedKind }) {
  /* Which action is selected. Everything below the picker is derived from it,
   * so switching the dropdown switches the form with no other bookkeeping.
   *
   * It starts as '' - no action - on purpose. Defaulting to Deposit would show
   * a working deposit form the moment the page opens, and a form that already
   * works is not somewhere people look for a dropdown. Starting empty makes
   * choosing the action the first thing you do, which is the only way the other
   * two get discovered. */
  const [kind, setKind] = useState(fixedKind ?? '')

  /* Both inputs are kept as the raw text the user typed, not as numbers.
   * Storing a number would fight the user: "2." and "" are both states you have
   * to be able to be in halfway through typing, and neither survives a round
   * trip through Number(). Convert once, on submit. */
  const [amountText, setAmountText] = useState('')
  const [toAccountText, setToAccountText] = useState('')

  /* The parsed request, held between "Submit" and "Yes, do it". Null means no
   * confirmation is open. Keeping the parsed cents here rather than re-reading
   * the text box on confirm means the figure that was shown is exactly the
   * figure that gets sent. */
  const [pending, setPending] = useState(null)

  const [busy, setBusy] = useState(false)     // true while a request is in flight
  const [error, setError] = useState(null)    // what went wrong, or null
  const [result, setResult] = useState(null)  // what succeeded, or null

  /* Derived, not state: looked up fresh each render, so it can never disagree
   * with the dropdown. Undefined while nothing is chosen - KINDS has no ''
   * key - and that absence is what the form below keys off. */
  const kindConfig = KINDS[kind]

  function handleKindChange(event) {
    setKind(event.target.value)
    // A message about the last deposit has no business sitting under a
    // half-filled transfer form.
    setError(null)
    setResult(null)
  }

  async function handleSubmit(event) {
    /* Without this the browser does what a form has always done: reload the
     * page with the fields in the URL. That would restart the whole React app
     * and throw away everything on this screen. */
    event.preventDefault()
    setError(null)
    setResult(null)

    /* ---------------------------------------------------------- validation */

    // parseDollars returns null for anything that is not a usable amount:
    // 0, a negative, empty text, "twenty", and "1.1" - cents are written with
    // two digits or not at all. See money.js.
    const cents = parseDollars(amountText)
    if (cents === null) {
      setError('Enter an amount above zero as whole dollars or two decimal places, for example 25 or 25.00')
      return
    }

    // Only read for a transfer; left as null otherwise so `send` gets a
    // consistent shape either way.
    let toAccountId = null
    if (kindConfig.needsDestination) {
      const parsed = Number(toAccountText.trim())
      // Number('') is 0 and Number('1.5') is 1.5, so check both that it is a
      // whole number and that it is above zero.
      if (!Number.isInteger(parsed) || parsed <= 0) {
        setError('Enter the destination account id - a whole number above zero')
        return
      }
      if (parsed === account.accountId) {
        setError('Choose a different account to transfer to')
        return
      }
      toAccountId = parsed
    }

    /* ------------------------------------------------------------- confirm */

    /* Everything is valid, so stop here and show what is about to happen.
     * Nothing has been sent yet. */
    setPending({ cents, toAccountId })
  }

  async function send() {
    const { cents, toAccountId } = pending
    setPending(null)
    setError(null)
    setBusy(true)
    try {
      /* One fresh id per submission attempt. If a double click gets two
       * requests away, they carry the same id and the backend refuses the
       * second instead of moving the money twice. Generating it here rather
       * than in state is deliberate: a retry after a failure is a new attempt
       * and should get a new id. */
      const clientTxnId = crypto.randomUUID()
      const response = await kindConfig.send(account, cents, toAccountId, clientTxnId)

      /* All three endpoints answer with `account` - the source account as it
       * stands now. Show that number. Never add `cents` to the balance we were
       * already holding: that is the frontend doing money arithmetic, and it
       * is wrong the moment anything else touches the account. */
      setResult(`${kindConfig.label} complete. New balance: ${formatCents(response.account.balance)}`)
      setAmountText('')
      setToAccountText('')
      onAccountChange?.(response.account)
    } catch (err) {
      // Every failure from lib/api.js is an ApiError carrying the backend's
      // own message, so there is one thing to show.
      setError(err.message)
    } finally {
      // Runs on success and on failure, so the button always comes back.
      setBusy(false)
    }
  }

  // Guard, so every line below can assume the account exists.
  if (!account) {
    return (
      <div className="card">
        <h1>Make a transaction</h1>
        <p className="hint">No account selected.</p>
      </div>
    )
  }

  return (
    <div>
      {/* Both of these belong to the page when it pinned the action: Deposit
       * has already said "Deposit" and already shown the account in its picker,
       * so repeating them here showed the same account twice. Standalone - with
       * the action picker - this component is the whole screen and needs them. */}
      {!fixedKind && <h1>Make a transaction</h1>}

      {/* ------------------------------------------- the account and the picker */}
      {!fixedKind && (
      <div className="card menu-head">
        <div>
          <strong>{accountLabel(account)}</strong>
          {/* Divide by 100 to display, never to calculate. */}
          <div className="balance-large">{formatCents(account.balance)}</div>
        </div>

        {!fixedKind && (
        <label className="kind-picker">
          Action
          {/* A controlled input: React owns the value. The value comes from
            * state, onChange writes state, the new state re-renders with the
            * new value. Pass `value` without `onChange` and the field looks
            * frozen, because you told React the value never changes. */}
          <select value={kind} onChange={handleKindChange}>
            {/* The empty first option is what makes the page open with nothing
              * chosen. Its value is '', which matches the initial state, so
              * this is the option the browser shows - and because it reads as
              * a prompt rather than as an action, the list is the obvious next
              * thing to open. It stays selectable, so you can back out. */}
            <option value="">Choose an action...</option>

            {/* Built from the same KINDS object the form below reads, so the
              * dropdown and the form can never drift apart. Object.entries
              * gives [key, value] pairs; `key` is React's identity for the
              * row and is separate from the `value` the <select> reports. */}
            {Object.entries(KINDS).map(([value, config]) => (
              <option key={value} value={value}>{config.label}</option>
            ))}
          </select>
        </label>
        )}
      </div>
      )}

      <ConfirmTransaction
        open={pending !== null}
        kind={kind === 'WITHDRAW' ? 'WITHDRAW' : kind === 'TRANSFER' ? 'TRANSFER' : 'DEPOSIT'}
        account={account}
        amountCents={pending?.cents ?? 0}
        recipient={pending?.toAccountId ? `account ${pending.toAccountId}` : null}
        busy={busy}
        onConfirm={send}
        onCancel={() => setPending(null)}
      />

      {/* --------------------------------------------------------- the form */}
      {/* The ternary is the two-way version of `{cond && <jsx/>}`: one branch
        * or the other, never both. There is no form at all until an action is
        * chosen, so there is no button to press by mistake and nothing to read
        * except the one instruction. */}
      {kindConfig ? (
        <form className="card" onSubmit={handleSubmit}>
          {/* `{cond && <jsx/>}` renders the right-hand side only when the left
            * is true; React draws nothing for false, null or undefined. This
            * one field is the only structural difference between the three. */}
          {kindConfig.needsDestination && (
            <label>
              Destination account id
              <input
                type="text"
                inputMode="numeric"
                value={toAccountText}
                onChange={(event) => setToAccountText(event.target.value)}
                placeholder="e.g. 2"
              />
            </label>
          )}

          <label>
            {/* The label text is data, so this is one field serving all three. */}
            {kindConfig.amountLabel}
            {/* type="text", not type="number". A number input silently allows
              * "1e5" and "-", spins the value on a stray scroll, and hands back
              * "" for anything it considers invalid - so you cannot tell a typo
              * from an empty box. parseDollars does the checking instead, in
              * one place, the same way for every field. */}
            <input
              type="text"
              inputMode="decimal"
              value={amountText}
              onChange={(event) => setAmountText(event.target.value)}
              placeholder="0.00"
              aria-describedby="amount-hint"
            />
            {/* The rules, before you break them. These are the server's actual
              * limits, not a guess: money.py caps a transaction at 1,000,000.00
              * and parseDollars refuses one decimal place. */}
            <span className="hint" id="amount-hint">
              $0.01 to $1,000,000.00. Whole dollars or two decimal places —
              25 or 25.00, not 25.0.
            </span>
          </label>

          {/* Nothing is checked while you type. A half-typed amount is not a
            * mistake, and telling someone "25.0 is wrong" as they are on their
            * way to 25.00 is noise. Validation happens in handleSubmit, and
            * this is where its verdict appears. */}
          {error && <p className="error">{error}</p>}
          {result && <p className="success">{result}</p>}

          {/* Bottom right. The wrapper is what does it: justify-content:
            * flex-end pushes the button to the end of the row, where a form in
            * a column would otherwise stretch it across the full width. */}
          <div className="form-actions">
            <button type="submit" disabled={busy}>
              {busy ? 'Working...' : kindConfig.submitLabel}
            </button>
          </div>
        </form>
      ) : (
        <p className="card hint">
          Choose an action above — deposit, withdraw or transfer — to get started.
        </p>
      )}
    </div>
  )
}
