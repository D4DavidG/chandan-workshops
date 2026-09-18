/* Who is logged in, and which accounts they have, for the whole app.
 *
 * On load this asks the backend whether the stored token is still good, rather
 * than assuming it is and letting the first real call fail. Until that answer
 * comes back `loading` is true and the router shows nothing, so a logged-in user
 * refreshing a page is never bounced to the login screen for a moment.
 *
 * The account list lives here rather than in a page because two separate things
 * need it: the nav bar, to decide whether to show the Accounts tab, and the home
 * page, to list them. Fetching it in both would mean two calls on every load and
 * two versions of the truth.
 *
 * IMPORTANT for whoever builds deposit, withdraw and transfer: those change a
 * balance, so call `refreshAccounts()` after a successful one or the nav and the
 * home page will keep showing the old number.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../lib/api'
import { AuthContext } from './auth-context'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [accounts, setAccounts] = useState([])
  // Set when the server rejected a token mid-session, so the sign-in form can
  // say why you are suddenly looking at it. Cleared on the next successful login.
  const [sessionExpired, setSessionExpired] = useState(false)
  // Whether anybody is actually signed in, readable from a callback that was
  // registered once. Only a session that existed can be said to have ended: a
  // visitor arriving with a stale token in storage was never signed in, and
  // telling them their session expired would be a lie about something they did
  // not do.
  const signedIn = useRef(false)
  // With no stored token there is nothing to check, so the app is ready at once
  // and the "checking" state never appears.
  const [loading, setLoading] = useState(() => Boolean(api.getToken()))

  // One place, so login, register, the load probe and logout do not each have to
  // remember to keep the ref in step with the state it mirrors.
  useEffect(() => {
    signedIn.current = Boolean(user)
  }, [user])

  const refreshAccounts = useCallback(async () => {
    const data = await api.listAccounts()
    setAccounts(data.accounts)
    return data.accounts
  }, [])

  /* Any 401 from any call, from anywhere in the app, lands here.
   *
   * A JWT cannot be revoked, but it can stop being accepted - it expires, or the
   * server restarts with a new signing key. When that happens the app must stop
   * claiming to be signed in, or RequireAuth keeps rendering pages whose every
   * request fails. Clearing `user` is what makes the guard redirect.
   */
  useEffect(() => {
    api.setSessionEndedHandler(() => {
      // Read through a ref, not through `user`. The handler is registered once
      // and would otherwise close over the user as it was on mount - always
      // null - so it could never tell an expiry from an arrival.
      if (signedIn.current) setSessionExpired(true)
      setUser(null)
      setAccounts([])
    })
    return () => api.setSessionEndedHandler(null)
  }, [])

  useEffect(() => {
    if (!api.getToken()) return
    api
      .me()
      .then((data) => {
        setUser(data.user)
        return refreshAccounts()
      })
      .catch(() => api.setToken(null)) // expired or invalid: start logged out
      .finally(() => setLoading(false))
  }, [refreshAccounts])

  // `remember` decides whether the token outlives the browser session.
  async function login(email, password, remember = false) {
    const data = await api.login(email, password)
    api.setToken(data.token, remember)
    setUser(data.user)
    setSessionExpired(false) // you are back in; stop saying the last one lapsed
    await refreshAccounts()
    return data.user
  }

  // adminCode is optional and only the admin register page sends one. The server
  // decides the role; whatever comes back in data.user.role is the real answer.
  async function register(name, email, password, adminCode) {
    const data = await api.register(name, email, password, adminCode)
    // Registering is a deliberate act on your own machine, so it remembers you.
    api.setToken(data.token, true) // register logs you straight in
    setUser(data.user)
    setAccounts([]) // a brand new user has none yet
    return data.user
  }

  async function updateProfile(changes) {
    const data = await api.updateProfile(changes)
    setUser(data.user)
    return data.user
  }

  function logout() {
    api.setToken(null)
    setUser(null)
    setAccounts([])
    // Leaving on purpose is not an expiry, so the sign-in form stays quiet.
    setSessionExpired(false)
  }

  const value = {
    user, accounts, loading, sessionExpired,
    login, register, logout, updateProfile, refreshAccounts,
    isAdmin: user?.role === 'ADMIN',
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
