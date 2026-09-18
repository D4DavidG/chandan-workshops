/* The brief's "Create Account Page" (7.2) is two things in this API: registering
 * a user (here) and opening a bank account for them (OpenAccount.jsx).
 *
 * One form for everybody. The team code field decides what kind of account you
 * get, and leaving it empty is the ordinary case:
 *
 *   empty code   -> customer account, no questions
 *   right code   -> admin account
 *   wrong code   -> ask whether they meant to make an ordinary account
 *
 * THE CODE IS NEVER CHECKED HERE. It is sent to the server, which compares it
 * against BANK_ADMIN_CODE and answers 403 if it does not match, creating nobody.
 * So "wrong code" is something we learn from that 403, not something this file
 * could work out - which is the point. A comparison written in this file would
 * ship inside the bundle for anyone to read, and it would stop nobody.
 *
 * On "yes, make an ordinary account" the whole request is sent again with no
 * code in it. The rejected code is not stored, not logged and not sent anywhere
 * a second time.
 */
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/auth-context'
import SecretInput from '../components/SecretInput'

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ name: '', email: '', password: '', teamCode: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [asking, setAsking] = useState(false)

  const dialogRef = useRef(null)
  const codeRef = useRef(null)

  /* A native <dialog> opened with showModal() traps focus, makes the rest of the
   * page inert and closes on Escape, all without a line of code here. Hand-
   * rolling those three is where home-made modals usually go wrong. */
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (asking && !dialog.open) dialog.showModal()
    if (!asking && dialog.open) dialog.close()
  }, [asking])

  const update = (key) => (event) => setForm({ ...form, [key]: event.target.value })

  // The one place an account actually gets created. `withCode` is false for the
  // ordinary path and for "yes, I meant an ordinary account".
  async function createAccount(withCode) {
    setError(null)
    setBusy(true)
    try {
      await register(
        form.name, form.email, form.password,
        withCode ? form.teamCode : undefined,
      )
      // Everybody lands on the home page; it shows them what to do next.
      navigate('/')
    } catch (err) {
      // 403 on this endpoint means one thing: the code did not match. Anything
      // else - a taken email is a 409 - is a real error and shown as one.
      if (withCode && err.status === 403) setAsking(true)
      else setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function handleSubmit(event) {
    event.preventDefault()
    createAccount(form.teamCode.trim() !== '')
  }

  function keepTrying() {
    setAsking(false)
    // Put them back in the field they need to fix, rather than at the top.
    requestAnimationFrame(() => codeRef.current?.focus())
  }

  return (
    <div className="card narrow">
      <h1>Register</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Name
          <input value={form.name} onChange={update('name')} required />
          <span className="hint">The name shown on your accounts.</span>
        </label>
        <label>
          Email
          <input type="email" value={form.email} onChange={update('email')} required />
          <span className="hint">This is what you will sign in with. One account per address.</span>
        </label>
        <SecretInput
          label="Password"
          value={form.password}
          onChange={update('password')}
          minLength={8}
          required
          hint="At least 8 characters. Longer is better than complicated."
        />
        <SecretInput
          label="Team code (optional)"
          value={form.teamCode}
          onChange={update('teamCode')}
          ref={codeRef}
          autoComplete="off"
          hint="Staff only. Leave this empty for an ordinary account."
        />
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? 'Creating...' : 'Create account'}</button>
      </form>
      <p>Already registered? <Link to="/login">Log in</Link></p>

      {/* onCancel covers Escape and the browser's own dismiss, so closing the
          dialog any way at all lands in the same place as pressing No. */}
      <dialog ref={dialogRef} onCancel={(e) => { e.preventDefault(); keepTrying() }}>
        <h2>That is not a valid team code</h2>
        <p>Are you sure you want to make an account?</p>
        <p className="hint">
          Yes creates an ordinary customer account and forgets the code you typed.
          No takes you back so you can correct it, or clear it.
        </p>
        <div className="row">
          <button type="button" onClick={() => { setAsking(false); createAccount(false) }}
                  disabled={busy}>
            Yes, make an ordinary account
          </button>
          <button type="button" className="secondary" onClick={keepTrying}>
            No, let me fix the code
          </button>
        </div>
      </dialog>
    </div>
  )
}
