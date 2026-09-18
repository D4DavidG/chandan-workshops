/* Who did what, to which account, why, and when.
 *
 * Read-only, and that is the design rather than a missing feature: every freeze,
 * unfreeze and adjustment appends one row and nothing anywhere removes one.
 * Every field here is persisted - in MongoDB it is a document in `audit_log`
 * carrying the same five values.
 *
 * Newest first. The server returns them oldest first, which is the right order
 * for a ledger and the wrong one for a column you are watching - after an
 * action you want to see it without scrolling.
 *
 * Only the five most recent are shown. The log never shrinks - nothing removes a
 * row, by design - so an unbounded list is one that gets longer every day and is
 * eventually the whole page. Five is what you want after doing something: did
 * that land. Anything older, you are looking for rather than glancing at, and
 * that is what the search is.
 *
 * The search filters in the browser rather than asking the server. The whole log
 * is already here, so it is instant and there is no endpoint to add. If this ever
 * holds thousands of rows, that stops being true and the filter moves server-side
 * behind a `q` parameter - this component is where that starts.
 */
import { useMemo, useState } from 'react'

const DEFAULT_SHOWN = 5

/* The server sends UTC; an admin in the office thinks in Eastern. Built once at
 * module level rather than per row, because constructing a DateTimeFormat is the
 * expensive part and there may be hundreds of rows.
 *
 * `America/New_York`, not a fixed -05:00: that is what makes the offset follow
 * daylight saving instead of being wrong for eight months of the year.
 * `timeZoneName` then prints EST or EDT, so the label is never a claim the
 * clock does not support. */
const EASTERN = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
})

function easternTime(iso) {
  if (!iso) return null
  const when = new Date(iso)
  return Number.isNaN(when.getTime()) ? null : EASTERN.format(when)
}

/* Everything on the row is searchable, including the account and actor numbers,
 * because "31" is how you look up what happened to an account and "ADJUST" is
 * how you find every correction. Built per entry once and reused for every
 * keystroke. */
function haystack(entry) {
  return [
    entry.action,
    entry.reason,
    entry.actorName ?? '',
    entry.accountOwnerName ?? '',
    `account #${entry.accountId}`,
    `${entry.accountId}`,
    `user #${entry.actorUserId}`,
    `${entry.actorUserId}`,
    easternTime(entry.createdAt) ?? '',
  ].join(' ').toLowerCase()
}

/* "Aaron Forrester's account #31", or just "account #31" when the name cannot
 * be resolved. The id is always shown: the name is a caption on it, and two
 * customers can share a name while two ids cannot. */
function whose(entry) {
  return entry.accountOwnerName
    ? `${entry.accountOwnerName}'s account #${entry.accountId}`
    : `account #${entry.accountId}`
}

function byWhom(entry) {
  return entry.actorName
    ? `by ${entry.actorName} (#${entry.actorUserId})`
    : `by user #${entry.actorUserId}`
}

// `entries` defaults to empty: a caller that has not loaded them yet, or cannot,
// should get the empty state rather than a crash. This component's whole job is
// to render a list, and no list is a short one.
export default function AdminAuditLog({ entries = [] }) {
  const [query, setQuery] = useState('')
  const [showAll, setShowAll] = useState(false)

  // Newest first, with the searchable text attached once rather than rebuilt on
  // every keystroke.
  const newestFirst = useMemo(
    () => entries.map((entry, index) => ({ entry, key: index, text: haystack(entry) })).reverse(),
    [entries],
  )

  const needle = query.trim().toLowerCase()
  const searching = needle !== ''
  const matches = searching ? newestFirst.filter((row) => row.text.includes(needle)) : newestFirst
  // Searching replaces the five rather than filtering within them - otherwise a
  // search that matched something older would appear to find nothing.
  const shown = searching || showAll ? matches : matches.slice(0, DEFAULT_SHOWN)
  const hidden = matches.length - shown.length

  if (entries.length === 0) {
    return <p className="hint">Nothing yet. Freeze or adjust an account and it appears here.</p>
  }

  return (
    <div className="audit">
      <label className="audit-search">
        Search the log
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Action, reason, account or user number"
        />
      </label>

      <p className="hint">
        {searching
          ? `${matches.length} of ${entries.length} entr${entries.length === 1 ? 'y' : 'ies'} match.`
          : showAll
            ? `All ${entries.length} entries, newest first.`
            : `The ${shown.length} most recent of ${entries.length}.`}
      </p>

      {shown.length === 0 ? (
        <p className="hint">Nothing in the log matches that.</p>
      ) : (
        <ol className="admin-log">
          {shown.map(({ entry, key }) => (
            <li key={key}>
              <span className="admin-log-action">{entry.action}</span>
              <span className="admin-log-where">
                {easternTime(entry.createdAt) ?? 'time not recorded'}
              </span>
              <span className="admin-log-where">
                {whose(entry)} · {byWhom(entry)}
              </span>
              <span>{entry.reason}</span>
            </li>
          ))}
        </ol>
      )}

      {/* Only while a search is not running: during a search the list is
          already everything that matches, and a "show all" under it would be
          offering to undo the search without saying so. */}
      {!searching && entries.length > DEFAULT_SHOWN && (
        <button type="button" className="secondary audit-more"
                onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Show the 5 most recent' : `List all ${entries.length} entries`}
        </button>
      )}
      {!searching && !showAll && hidden > 0 && (
        <span className="hint"> {hidden} older {hidden === 1 ? 'entry' : 'entries'} hidden.</span>
      )}
    </div>
  )
}
