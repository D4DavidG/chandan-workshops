/* A text field whose contents are hidden, with an eye to reveal them.
 *
 * Hiding what you type stops somebody reading it over your shoulder; it does
 * nothing else, and it is a common cause of typos in exactly the fields where a
 * typo is most annoying. Letting people look is the usual fix.
 *
 * The icon is drawn here rather than being an emoji. Emoji render differently on
 * every platform - on some, the "see-no-evil monkey" is a face rather than a
 * crossed-out eye - so the one state that has to read as "off" could not be
 * relied on. Two paths in an <svg> always look the same everywhere.
 *
 * The toggle is a real <button type="button">. Without the type it would default
 * to "submit" and revealing the password would send the form.
 */
import { useState } from 'react'

function EyeIcon({ crossed }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         aria-hidden="true" focusable="false">
      <path d="M1.5 12S5.2 5.5 12 5.5 22.5 12 22.5 12 18.8 18.5 12 18.5 1.5 12 1.5 12Z" />
      <circle cx="12" cy="12" r="3.2" />
      {/* Shown while the text is visible, so the icon says what pressing it
          again would do: put the cover back. */}
      {crossed && <line x1="3.5" y1="20.5" x2="20.5" y2="3.5" />}
    </svg>
  )
}

// `ref` is taken as an ordinary prop and handed to the input. React 19 allows
// that directly; before 19 this needed forwardRef.
export default function SecretInput({ label, value, onChange, hint, ref, ...rest }) {
  const [revealed, setRevealed] = useState(false)

  return (
    <label>
      {label}
      <span className="secret-field">
        <input
          ref={ref}
          type={revealed ? 'text' : 'password'}
          value={value}
          onChange={onChange}
          {...rest}
        />
        <button
          type="button"
          className="reveal"
          onClick={() => setRevealed(!revealed)}
          /* The control is an icon, so it needs a name of its own for anyone not
           * looking at it. aria-pressed is what says which way it is currently
           * set - "Show" alone would not tell a screen reader it is a toggle. */
          aria-label={revealed ? 'Hide password' : 'Show password'}
          aria-pressed={revealed}
        >
          <EyeIcon crossed={revealed} />
        </button>
      </span>
      {hint && <span className="hint">{hint}</span>}
    </label>
  )
}
