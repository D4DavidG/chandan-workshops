/* Money is an integer number of cents everywhere except on screen.
 *
 * 123456 is 1,234.56. The backend refuses fractional numbers and strings
 * outright, so the only safe move is to keep cents in state and convert at the
 * edges: `formatCents` on the way to the screen, `parseDollars` on the way in
 * from an input. Never add, subtract or compare dollar values - do that in
 * cents, and never re-derive a balance in the browser. Every write endpoint
 * returns the new authoritative account; display that.
 */

/** 123456 -> "$1,234.56" */
export function formatCents(cents) {
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

/**
 * "1,234.56" -> 123456. Returns null if the text is not a usable amount, so a
 * caller can show a message instead of sending something the backend refuses.
 *
 * Exactly two forms are accepted, before an optional "$", commas and spaces:
 *
 *     "1"      -> 100      a whole number of dollars
 *     "1.10"   -> 110      dollars and cents, two digits after the point
 *
 * and everything else is null, including "1.1". One digit after the point is
 * refused rather than read as ten cents, because the two readings of it -
 * "$1.10" and "I have not finished typing" - are indistinguishable here, and
 * guessing wrong is a tenfold error. Asking for the second digit costs one
 * keystroke; guessing costs real money.
 *
 * Also null: "0", "-5", "1.005", "", "twenty", and anything with a sign or an
 * exponent. The backend refuses all of them too - this is the same rule stated
 * early, so the message comes from the field rather than from a failed request.
 */
export function parseDollars(text) {
  // "$1,234.56" and "1234.56" are the same amount typed by different people.
  // Formatting is not part of the rule, so it is removed before the rule runs.
  const cleaned = String(text).trim().replace(/[$,\s]/g, '')

  // \d+ has no sign and no exponent, so "-5" and "1e3" never reach Number().
  // The group is all-or-nothing: a point must be followed by exactly 2 digits.
  if (!/^\d+(\.\d{2})?$/.test(cleaned)) return null

  // The text is now at most 2 decimal places, so this multiplication is exact
  // for any amount worth typing; Math.round only cleans up float noise such as
  // 1.10 * 100 === 110.00000000000001.
  const cents = Math.round(Number(cleaned) * 100)

  // Zero is not an amount. "0" and "0.00" both land here.
  return cents > 0 ? cents : null
}

/** "2026-09-15T14:03:11.482913+00:00" -> "Sep 15, 2026, 2:03 PM" */
export function formatDate(iso) {
  return new Date(iso).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
}
