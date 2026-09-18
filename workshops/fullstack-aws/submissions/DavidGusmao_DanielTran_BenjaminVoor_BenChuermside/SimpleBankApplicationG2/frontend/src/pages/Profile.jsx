/* Your own details, and editing them. Reached by clicking your name in the nav.
 *
 * Works the same for a customer and an admin - the only difference on screen is
 * the role badge. Role is not editable here and the server would refuse it
 * anyway: a profile edit that could set a role is how privilege escalation
 * usually gets in. */
import { useState } from 'react'
import { useAuth } from '../context/auth-context'
import { formatDate } from '../lib/money'

export default function Profile() {
  const { user, accounts, isAdmin, updateProfile } = useAuth()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({ name: user.name, email: user.email })
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  const update = (key) => (event) => setForm({ ...form, [key]: event.target.value })

  function startEditing() {
    setForm({ name: user.name, email: user.email }) // discard any abandoned edit
    setError(null)
    setSaved(false)
    setEditing(true)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      // Send only what actually changed. The server leaves an omitted field
      // alone, so an unchanged email never has to be checked against itself.
      const changes = {}
      if (form.name !== user.name) changes.name = form.name
      if (form.email !== user.email) changes.email = form.email
      if (Object.keys(changes).length > 0) await updateProfile(changes)
      setEditing(false)
      setSaved(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card profile">
      {/* Title left, edit right, on one line - so the button is somewhere
          predictable whether the card is short or long. */}
      <div className="profile-head">
        <h1>My details</h1>
        {!editing && (
          <button className="edit-circle lift" onClick={startEditing}>Edit</button>
        )}
      </div>

      {editing ? (
        <form onSubmit={handleSubmit}>
          <label>
            Name
            <input value={form.name} onChange={update('name')} required />
            <span className="hint">Cannot be left blank.</span>
          </label>
          <label>
            Email
            <input type="email" value={form.email} onChange={update('email')} required />
          </label>
          <p className="hint">
            Your email is what you log in with. Changing it here changes that too,
            and the old address stops working straight away.
          </p>
          {error && <p className="error">{error}</p>}
          <div className="row">
            <button type="submit" disabled={busy}>{busy ? 'Saving...' : 'Save'}</button>
            <button type="button" className="secondary" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          {/* One boxed row per fact, label left and value right. Wrapping each
              dt/dd pair in a div is allowed in a <dl> and is what lets the pair
              be laid out as a single row. */}
          <dl className="detail-rows">
            <div><dt>Name</dt><dd>{user.name}</dd></div>
            <div><dt>Email</dt><dd>{user.email}</dd></div>
            <div>
              <dt>Role</dt>
              <dd>{user.role}{isAdmin && <span className="nav-role">ADMIN</span>}</dd>
            </div>
            <div><dt>Member since</dt><dd>{formatDate(user.createdAt)}</dd></div>
            <div><dt>Accounts</dt><dd>{accounts.length}</dd></div>
          </dl>
          {saved && <p className="hint">Saved.</p>}
        </>
      )}
    </div>
  )
}
