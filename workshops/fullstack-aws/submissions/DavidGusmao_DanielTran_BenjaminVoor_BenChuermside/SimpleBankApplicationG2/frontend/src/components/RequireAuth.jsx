/* Wraps the routes that need a token. An admin-only route adds admin; a route
 * that only makes sense for somebody who banks here adds customer.
 *
 * This is convenience, not security: the backend checks the token and the role
 * on every single request, and hiding a link has never stopped anybody. */
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/auth-context'

export default function RequireAuth({ admin = false, customer = false, children }) {
  const { user, loading, isAdmin } = useAuth()
  const location = useLocation()

  if (loading) return null // the "is my stored token still good" check is in flight
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />
  if (admin && !isAdmin) return <Navigate to="/" replace />
  // An admin holds no accounts, so opening one or transferring between them is
  // not a page they can complete. Send them where their powers actually are.
  if (customer && isAdmin) return <Navigate to="/admin" replace />
  return children
}
