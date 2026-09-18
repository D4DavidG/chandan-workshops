import { useEffect, useMemo, useState } from 'react'
import * as api from '../lib/api'
import { formatCents, formatDate } from '../lib/money'

/* The ledger for one account: the rows, the pager, and nothing else.
 *
 * This is the History page's inner half, the way TransactionMenu is the inner
 * half of Deposit and Withdraw. It renders no card, no title and no account
 * header, because History.jsx has already put all three around it - which is
 * what makes the four money pages look like one another.
 *
 * The account id arrives as a prop. It does not read the URL: History owns
 * which account is selected, and a component that read both would have two
 * answers to the same question.
 */
export default function Transactions({ accountId }) {
  /* Starts at page one every time. History gives this component a `key` of the
   * account id, so switching account remounts it rather than reusing it - which
   * is how the page number resets without an effect reaching in to set it.
   * Without that, leaving an account you were three pages into would land on
   * page three of one that has a single page, and the table would come back
   * empty. */
  const [page, setPage] = useState(1)
  const [pageSize] = useState(10)
  const [items, setItems] = useState([])
  const [totalPages, setTotalPages] = useState(1)
  const [account, setAccount] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!accountId) return

    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)

      try {
        const accountData = await api.getAccount(Number(accountId))
        const data = await api.listTransactions(Number(accountId), { page, pageSize })

        if (!cancelled) {
          setAccount(accountData.account)
          setItems(data.items)
          setTotalPages(data.totalPages || 1)
        }
      } catch (err) {
        if (!cancelled) setError(err?.message || 'Unable to load transactions.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [accountId, page, pageSize])

  const rows = useMemo(() => {
    if (!account) return []

    let runningBalance = account.balance
    return items.map((txn) => {
      const result = runningBalance
      runningBalance -= txn.signedAmount
      return { ...txn, resultingBalance: result }
    })
  }, [account, items])

  if (loading) return <p className="hint">Loading activity...</p>
  if (error) return <p className="error">{error}</p>

  return (
    <>
      <p className="hint">
        Showing {items.length} result{items.length === 1 ? '' : 's'} on page {page}.
      </p>

      {items.length === 0 ? (
        <p>No transactions yet.</p>
      ) : (
        <>
          <table className="ledger">
            <thead>
              <tr>
                <th>Date</th>
                <th>Type</th>
                <th>Amount</th>
                <th>Resulting balance</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((txn) => (
                <tr key={txn.txnId}>
                  <td>{formatDate(txn.createdAt)}</td>
                  <td>{txn.type}</td>
                  <td className={txn.signedAmount >= 0 ? 'credit' : 'debit'}>
                    {formatCents(txn.signedAmount)}
                  </td>
                  <td className="balance">{formatCents(txn.resultingBalance)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="row pager">
            <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
              Previous
            </button>
            <span className="hint">Page {page} of {totalPages}</span>
            <button type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>
              Next
            </button>
          </div>
        </>
      )}

    </>
  )
}
