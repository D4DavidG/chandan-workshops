/* The sign-in form. Lives here rather than on the login page because the home
 * page shows the same form, and two copies would drift apart.
 *
 * `onDone` is where to go afterwards - both callers send people to the home
 * page, but the form should not be the thing that decides that.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/auth-context'
import SecretInput from './SecretInput'

export default function LoginForm({ onDone }) {
  const { login, sessionExpired } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email, password, remember)
      onDone()
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {/* Being bounced here mid-task with no explanation reads as a bug. This
        * appears wherever the form does, including the home page, and only
        * after a session that actually existed was rejected. */}
      {sessionExpired && !error && (
        <p className="hint">Your session has ended. Please sign in again.</p>
      )}

      <div className="field-row">
        <label>
          Email
          <input type="email" value={email} autoComplete="username"
                 onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <SecretInput
          label="Password"
          value={password}
          autoComplete="current-password"
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>

      {/* A checkbox is laid out along the line, not stacked like the fields
          above, so it opts out of the column `label` gets by default. */}
      <label className="checkbox">
        <input type="checkbox" checked={remember}
               onChange={(e) => setRemember(e.target.checked)} />
        Remember me
      </label>

      {error && <p className="error">{error}</p>}
      <button type="submit" className="lift" disabled={busy}>
        {busy ? 'Signing in...' : 'Sign in'}
      </button>
      <p>Don't have an account? <Link to="/register">Register now</Link></p>
    </form>
  )
}
