/* The admin console: what an ADMIN may do that a customer may not, which is
 * freeze an account, correct a balance, and read the record of both.
 *
 * An admin holds no accounts of their own - the rule is in
 * BankService.open_account - so there is nothing here about opening one or
 * moving money the ordinary way. Everything on this page is done TO somebody
 * else's account, which is why every action needs a written reason and lands in
 * the log on the left.
 *
 * RequireAuth keeps a customer off this route, but that is convenience and not
 * security: the backend checks the role on every one of these calls and refuses
 * them whatever this page happens to render.
 *
 * Deliberately not here: GET /api/admin/users. It is a table of names that
 * demonstrates nothing the account list does not. */
import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../context/auth-context'
import * as api from '../lib/api'
import AdminAccountRow from '../components/AdminAccountRow'
import AdminAuditLog from '../components/AdminAuditLog'
import './Admin.css'

/* One account against the search box and the type filter.
 *
 * The name match is case-insensitive and matches anywhere, so "for" finds
 * Aaron Forrester. A query that is all digits also matches the account id,
 * because an admin arriving from the audit log has an id in hand rather than a
 * name - the log records what was done to #12, not to Justin. */
function matches(account, query, kind) {
  if (kind !== 'ALL' && account.accountType !== kind) return false
  const q = query.trim().toLowerCase()
  if (q === '') return true
  return account.userName.toLowerCase().includes(q) || String(account.accountId) === q
}

export default function Admin() {
  const { refreshAccounts } = useAuth()
  const [accounts, setAccounts] = useState([])
  const [entries, setEntries] = useState([])
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('ALL')

  /* One reload for all of it, because any admin action moves all of it: the
   * account's balance or status, the audit row that recorded it, and the
   * reconciliation that counts it. Refreshing only the row that changed would
   * leave the other two quietly stale, and a stale reconciliation is worse than
   * none - it is a correctness claim about numbers it has not re-read. */
  const load = useCallback(() => {
    /* Reconciliation is deliberately NOT awaited with the rest. It reads every
     * account's ledger, so it is the slowest call on the page, and holding the
     * render for it meant staring at "Loading..." while the two fast calls sat
     * finished. It lands on its own and fills the banner in.
     *
     * A failure here only empties the banner. It is a report ABOUT the data,
     * not the data, so it must not take the page down with it.
     *
     * The old report is left on screen while the new one is in flight rather
     * than blanked first: after a freeze the number is about to be the same,
     * and a banner that empties and refills reads as a fault. */
    api.adminReconciliation().then(setReport).catch(() => setReport(null))

    return Promise.all([api.adminAccounts(), api.adminAudit(), refreshAccounts()])
      .then(([accountList, audit]) => {
        setAccounts(accountList.accounts)
        setEntries(audit.entries)
        setError(null)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [refreshAccounts])

  useEffect(() => {
    load()
  }, [load])

  if (loading) return <p>Loading...</p>
  if (error) return <p className="error">{error}</p>

  /* Nothing is listed until something is typed.
   *
   * Every row is a component holding its own state and two forms, so rendering
   * the whole roster costs real time and gets worse with every account opened -
   * and an admin arrives here looking for ONE account, not for a list of all of
   * them. The type filter alone does not open the gate either: "all the
   * checking accounts" is the same dump with fewer rows.
   *
   * Note this trims what is RENDERED, not what is fetched - the accounts are
   * already in memory. Moving the search to the server is the next step if the
   * roster ever gets big enough for the fetch itself to hurt. */
  const searching = query.trim().length > 0
  const visible = searching ? accounts.filter((account) => matches(account, query, kind)) : []

  return (
    <div className="admin theme-admin">
      <h1>Admin</h1>

      {/* The running proof that no code path has changed a balance without
        * writing a matching ledger entry. It should read balanced on every
        * refresh; the day it does not, this is the first thing to look at.
        * The state is in the words, not only in the colour. */}
      {/* Held open while the report is in flight, so the page does not jump when
        * it arrives a moment after everything else. */}
      {!report ? (
        <p className="admin-reconciliation hint">Checking every balance against its ledger…</p>
      ) : (
        <p className={report.balanced ? 'admin-reconciliation hint' : 'admin-reconciliation error'}>
          {report.balanced
            ? `Balanced — ${report.checked} accounts checked, every balance matches its ledger.`
            : `Not balanced — ${report.discrepancies.length} of ${report.checked} accounts disagree with their ledger.`}
        </p>
      )}

      <div className="admin-layout">
        <section>
          <h2>Audit log</h2>
          <AdminAuditLog entries={entries} />
        </section>

        <section>
          <h2>Accounts</h2>
          <div className="admin-filters">
            <label>
              Search by name or id
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Aaron, or 12"
              />
            </label>
            <label>
              Type
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="ALL">All</option>
                <option value="CHECKING">Checking</option>
                <option value="SAVINGS">Savings</option>
                {/* CREDIT exists in the shared data. Without this the filter
                    cannot reach those accounts, only "All" shows them. */}
                <option value="CREDIT">Credit</option>
              </select>
            </label>
          </div>
          {!searching ? (
            <p className="hint">
              {accounts.length} accounts loaded. Type a name or an account id above to
              find one.
            </p>
          ) : visible.length === 0 ? (
            <p>Nothing matches that search.</p>
          ) : (
            <>
              <p className="hint">
                {visible.length} of {accounts.length} accounts match.
              </p>
              {visible.map((account) => (
                <AdminAccountRow key={account.accountId} account={account} onChanged={load} />
              ))}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
