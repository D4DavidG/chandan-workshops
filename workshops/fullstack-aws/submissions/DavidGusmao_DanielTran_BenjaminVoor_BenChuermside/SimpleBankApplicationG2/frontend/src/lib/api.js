/* The one place that talks to the backend.
 *
 * Every call goes through `request`, so the token header, the JSON encoding and
 * the error shape are handled once rather than in every page. Pages should call
 * the named functions below and never call fetch directly - that way, when the
 * auth scheme or the base URL changes, it changes here.
 *
 * Amounts are integer cents, in and out. See src/lib/money.js.
 */

const BASE = '/api' // the dev server proxies this to the Python backend

/* Where the token is kept is what "Remember me" actually changes:
 *
 *   localStorage    ticked    - survives closing the browser
 *   sessionStorage  unticked  - gone when the tab closes
 *
 * Either way the token itself expires a week after it was issued, so remember
 * me buys a longer-lived *store*, not a longer-lived token; a 401 from any call
 * means it has gone stale and the user logs in again.
 *
 * Every access is wrapped, because both stores throw rather than return null in
 * some private-browsing modes. A session that cannot be persisted should still
 * work until the tab closes, not crash on load.
 */
const TOKEN_KEY = 'bank.token'

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token, remember = false) {
  try {
    // Clear both first. Without this, logging in without "remember me" would
    // leave an older long-lived token behind for getToken() to find later.
    localStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(TOKEN_KEY)
    if (token) (remember ? localStorage : sessionStorage).setItem(TOKEN_KEY, token)
  } catch {
    /* nothing can be stored; the session lasts until the page is closed */
  }
}

/* Thrown by every failed call. The backend answers every failure with the same
 * { error } shape, so there is exactly one thing to unwrap. `status` is kept so
 * a caller can tell "your token expired" (401) from "that is not allowed" (403)
 * without reading the message. */
export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/* What to do when the server says the token is no good. AuthContext registers a
 * function here on mount; until it does, a 401 still clears the stored token.
 *
 * A module-level slot rather than a prop, because `request` is called from
 * everywhere and threading a callback through every page is exactly the kind of
 * repetition that ends with one page forgetting.
 */
let onSessionEnded = null

export function setSessionEndedHandler(fn) {
  onSessionEnded = fn
}

/* Paths where a 401 is an ANSWER, not an expired session.
 *
 * A failed login is a 401 by design - it means "those credentials are wrong",
 * not "your session ended" - so it must not tear down a session, and the form
 * must be left to show the message itself.
 */
const CREDENTIAL_PATHS = ['/auth/login', '/auth/register']

async function request(method, path, body) {
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  // Every response from this API is JSON, but a crashed or missing server is
  // not, so do not let a parse failure surface as an unreadable stack trace.
  let payload
  try {
    payload = await response.json()
  } catch {
    throw new ApiError(response.status, 'the server did not answer with JSON')
  }

  if (!response.ok) {
    /* A 401 on any other route means the token is gone, expired, or was signed
     * with a key this server no longer has - restarting the backend without
     * BANK_SECRET set does exactly that, so this is a normal Tuesday and not an
     * edge case.
     *
     * Without this, the app kept rendering as though you were signed in - your
     * name in the nav, the old account list on screen - while every request
     * failed, and the reason arrived as a small red line next to whichever
     * button you happened to press. Drop the dead token and let the guard send
     * you to the sign-in form.
     */
    if (response.status === 401 && !CREDENTIAL_PATHS.some((p) => path.startsWith(p))) {
      setToken(null)
      onSessionEnded?.()
    }
    throw new ApiError(response.status, payload.error ?? 'request failed')
  }
  return payload
}

const get = (path) => request('GET', path)
const post = (path, body) => request('POST', path, body)

/* ------------------------------------------------------------------ auth */

export const health = () => get('/health')
// adminCode is the shared code from the admin register page. It is only ever
// checked on the server - the copy in this file is just what the form collected,
// and sending the wrong one is a 403 that creates nobody.
export const register = (name, email, password, adminCode) =>
  post('/auth/register', adminCode ? { name, email, password, adminCode }
                                   : { name, email, password })

export const login = (email, password) => post('/auth/login', { email, password })
export const me = () => get('/auth/me')

// Edit your own name or email. Which user gets edited comes from the token, so
// there is no id to pass. Send only what changed; an omitted field is left alone.
export const updateProfile = (changes) => post('/auth/me', changes)

/* -------------------------------------------------------------- accounts */

export const listAccounts = () => get('/accounts')
export const getAccount = (accountId) => get(`/accounts/${accountId}`)

// accountType is 'CHECKING' or 'SAVINGS'; openingBalance is cents.
export const openAccount = (accountType, openingBalance = 0) =>
  post('/accounts', { accountType, openingBalance })

/* ---------------------------------------------------------- transactions */

// clientTxnId is optional but worth sending: the backend refuses a repeat of an
// id it has already accepted, so a double-clicked button cannot move the money
// twice. crypto.randomUUID() per submission attempt is enough.
export const deposit = (accountId, amount, clientTxnId) =>
  post(`/accounts/${accountId}/deposit`, { amount, clientTxnId })

export const withdraw = (accountId, amount, clientTxnId) =>
  post(`/accounts/${accountId}/withdraw`, { amount, clientTxnId })

export const transfer = (fromAccountId, toAccountId, amount, clientTxnId) =>
  post('/transfers', { fromAccountId, toAccountId, amount, clientTxnId })

// Send to a person rather than to an account number. The server resolves them
// to their primary account, so the browser never holds anyone else's account id.
export const transferToUser = (fromAccountId, toUserId, amount, clientTxnId) =>
  post('/transfers', { fromAccountId, toUserId, amount, clientTxnId })

// People the caller could pay, matched on name or email. Two characters minimum;
// anything shorter comes back empty rather than returning half the roster.
export const searchUsers = (q) =>
  get(`/users/search?q=${encodeURIComponent(q)}`)

// Comes back as a page envelope: { items, page, pageSize, total, totalPages }.
export function listTransactions(accountId, { page = 1, pageSize = 20, type } = {}) {
  const query = new URLSearchParams({ page, pageSize })
  if (type) query.set('type', type)
  return get(`/accounts/${accountId}/transactions?${query}`)
}

/* ------------------------------------------------------------------ admin */
/* These answer "admin role required" unless the logged-in user's role is ADMIN. */

export const adminUsers = () => get('/admin/users')
export const adminAccounts = () => get('/admin/accounts')
export const adminAudit = () => get('/admin/audit')
export const adminReconciliation = () => get('/admin/reconciliation')

export const adminFreeze = (accountId, frozen, reason) =>
  post(`/admin/accounts/${accountId}/freeze`, { frozen, reason })

// direction is 'CREDIT' or 'DEBIT'; reason must be at least 10 characters.
export const adminAdjust = (accountId, amount, direction, reason) =>
  post(`/admin/accounts/${accountId}/adjust`, { amount, direction, reason })
