/* How an account is named and coloured. One place, because the home page, the
 * accounts list, the detail page and every picker all have to agree - an
 * account that is teal in one list and violet in another is worse than one
 * with no colour at all.
 */

/** "Checking...23" - the type, then the number that tells two of them apart. */
export function accountLabel(account) {
  const type = account.accountType.charAt(0) + account.accountType.slice(1).toLowerCase()
  return `${type}...${account.accountId}`
}

/* Colour carries the account TYPE, not just identity: blues and greens are
 * current accounts, oranges and reds are savings, and credit is its own thing.
 * So the palette tells you what kind of account you are looking at before you
 * read the label, and the shade within it tells two of the same kind apart.
 *
 * Every shade below clears 4.5:1 with white at the lightest end of its
 * gradient - the ratios are in index.css beside each rule. */
const CHECKING_SHADES = ['c0', 'c1', 'c2', 'c3']  // teal, emerald, cyan, blue
const SAVINGS_SHADES = ['s0', 's1', 's2', 's3']   // amber, orange, rose, red

/**
 * The colour class suffix. Credit is always the same, because it is a different
 * product rather than another account of the same kind. The others are picked
 * by accountId, so an account keeps its shade when another one is closed.
 */
export function accountTone(account) {
  if (account.accountType === 'CREDIT') return 'credit'
  const shades = account.accountType === 'SAVINGS' ? SAVINGS_SHADES : CHECKING_SHADES
  return shades[account.accountId % shades.length]
}

export const isCredit = (account) => account.accountType === 'CREDIT'
