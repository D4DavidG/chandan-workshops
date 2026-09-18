/* Light or dark, and remembering which.
 *
 * Light is the default, and the operating system is still listened to. Three
 * states make that work, not two:
 *
 *   'light' / 'dark'  the viewer chose, and their choice overrides the OS
 *   nothing stored    follow the OS, which the CSS does by itself
 *
 * Choosing the mode your OS already asks for CLEARS the stored value rather
 * than pinning it. Without that, one press of the button while testing would
 * freeze the site in that mode for good, and changing your OS theme afterwards
 * would appear to do nothing.
 */
const KEY = 'bank.theme'

/** What the OS asks for. Light unless it says otherwise - that is the default. */
export function systemTheme() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** What is stored, or null for "follow the OS". */
export function storedTheme() {
  try {
    const value = localStorage.getItem(KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    // Private browsing can throw on read. No preference is a fine answer.
    return null
  }
}

/** What the page is actually showing right now, stored or not. */
export function activeTheme() {
  return storedTheme() ?? systemTheme()
}

export function applyTheme(theme) {
  const matchesSystem = theme === systemTheme()
  try {
    if (matchesSystem) localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, theme)
  } catch {
    /* the choice lasts until the page is closed */
  }
  // With no attribute the CSS falls back to the media query, which is exactly
  // "follow the OS". Setting data-theme="light" would also work, but it would
  // stop tracking the OS if it changed later in the session.
  if (matchesSystem) document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', theme)
}
