/* Type a name, pick a person. The list narrows as you type.
 *
 * Two things stop this hammering the server on every keystroke:
 *
 *   - a 250ms debounce, so "benjamin" is one request rather than eight;
 *   - a sequence number, so a slow reply for "ben" cannot land after the reply
 *     for "benjamin" and overwrite the newer, narrower list. Requests do not
 *     come back in the order they were sent, and the last one to *arrive* is
 *     the wrong thing to trust.
 */
import { useEffect, useRef, useState } from 'react'
import * as api from '../lib/api'

export default function UserSearch({ selected, onSelect }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const latest = useRef(0)

  const text = query.trim()
  const longEnough = text.length >= 2

  /* Results are only ever *rendered* when the query is long enough, so the
   * effect never has to clear them on the way down. That is what keeps it from
   * calling setState the moment it runs, which would start a second render
   * before the first had finished. */
  const shown = longEnough ? results : []

  useEffect(() => {
    if (selected || !longEnough) return   // nothing to ask for
    const mine = ++latest.current
    const timer = setTimeout(() => {
      setSearching(true)
      api
        .searchUsers(text)
        .then((data) => {
          if (mine === latest.current) setResults(data.users)
        })
        .catch(() => {
          if (mine === latest.current) setResults([])
        })
        .finally(() => {
          if (mine === latest.current) setSearching(false)
        })
    }, 250)
    return () => clearTimeout(timer)
  }, [text, longEnough, selected])

  if (selected) {
    return (
      <div className="picked">
        <div>
          <strong>{selected.name}</strong>
          <span className="hint">{selected.email}</span>
        </div>
        <button type="button" className="secondary"
                onClick={() => { onSelect(null); setQuery(''); setResults([]) }}>
          Change
        </button>
      </div>
    )
  }

  return (
    <div className="user-search">
      <label>
        Send to
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name or email"
          autoComplete="off"
        />
      </label>

      {longEnough && (
        <ul className="results">
          {shown.map((person) => (
            <li key={person.userId}>
              {/* A button, not a div with onClick: it has to be reachable by
                  keyboard, and Tab through a list of divs reaches nothing. */}
              <button type="button" onClick={() => onSelect(person)}>
                <strong>{person.name}</strong>
                <span className="hint">{person.email}</span>
              </button>
            </li>
          ))}
          {shown.length === 0 && (
            <li className="hint no-match">
              {searching ? 'Searching...' : 'Nobody matches that.'}
            </li>
          )}
        </ul>
      )}
      {text.length === 1 && (
        <p className="hint">Keep typing — two letters at least.</p>
      )}
    </div>
  )
}
