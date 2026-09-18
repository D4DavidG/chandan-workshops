/* The context object and its hook, kept apart from the provider component.
 *
 * A file that exports both a component and a plain function breaks React Fast
 * Refresh, which is why this is not all in AuthContext.jsx. Import `useAuth`
 * from here; import `AuthProvider` from AuthContext.jsx. */
import { createContext, useContext } from 'react'

export const AuthContext = createContext(null)

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
