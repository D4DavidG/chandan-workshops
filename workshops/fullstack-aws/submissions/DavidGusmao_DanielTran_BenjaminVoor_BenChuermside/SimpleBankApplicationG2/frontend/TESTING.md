# Manual test plan — frontend

Four sections, one owner each. Automated tests would catch more, but this app
doesn't have frontend tests yet, so this is the checklist a human runs before a
demo. Check a box only after seeing the behaviour, not after reading the code.

Seed login: `aaron.forrester@example.com` / `BankDemo123!`.
Run: `python server.py`, then `cd frontend && npm run dev`.

---

## Tester A — Auth & profile

Covers: `Login.jsx`, `Register.jsx`, `Home.jsx` (landing state), `Profile.jsx`,
`RequireAuth.jsx`.

- [ ] Register a new user with a valid name/email/password → logged in, lands on `/`
- [ ] Register with an email already in use → clear error, no account created
- [ ] Register with a blank field → error, not a silent no-op
- [ ] Register with a wrong `adminCode` → 403-style error, no user created
- [ ] Register with the correct `adminCode` (if configured) → user is ADMIN, nav goes red
- [ ] Log in with correct credentials → redirected to `/`
- [ ] Log in with wrong password/email → error shown, field not just red
- [ ] "Remember me" checked → token in `localStorage`, survives closing the browser
- [ ] "Remember me" unchecked → token in `sessionStorage`, gone after closing the browser
- [ ] Visiting `/accounts` (or any protected route) while logged out → redirected to login, not a blank/broken page
- [ ] Refresh the page while logged in → still logged in (`/api/auth/me` check on load)
- [ ] Edit profile: change name only → saved, email untouched
- [ ] Edit profile: change email only → saved, can log in with new email, old email fails
- [ ] Edit profile: submit with both fields blank → 400 shown, nothing erased
- [ ] Edit profile: set email to one already used by someone else → error
- [ ] Log out → redirected to public landing, protected routes now bounce to login

---

## Tester B — Accounts & money movement

Covers: `Accounts.jsx`, `AccountDetails.jsx`, `OpenAccount.jsx`,
`TransactionMenu.jsx` / `Deposit.jsx` / `Withdraw.jsx` / `Transfer.jsx` (whichever
the team settled on), `Transactions.jsx`.

- [ ✅ ] Open a CHECKING account with a zero opening balance → appears in account list
- [ ✅ ] Open a SAVINGS account with a non-zero opening balance → balance shown matches, and a DEPOSIT transaction exists for it
- [ ✅ ] Open an account with an invalid type or a bad opening balance → error, no account created
- [ ✅ ] Account details page shows current balance, type, and status (frozen or not)
- [ ✅ ] Deposit a valid amount → success message shows the *server's* new balance, not a locally-added one
- [ ✅ ] Deposit a zero or negative amount → rejected with a clear message
- [ ✅ ] Deposit an amount like `25.00` typed as dollars → converts correctly to cents (or is refused, per the API rule) — never silently wrong by 100x

<br></br>
- [ ❓ ] Double-click submit on a deposit (or double-submit quickly) → only one transaction is recorded (`clientTxnId` idempotency)

    *I can't click that fast, or my internet is too good*
<br></br>

- [ ✅ ] Withdraw an amount ≤ available balance → succeeds, balance updates
- [ ✅ ] Withdraw more than the balance → "insufficient funds" error, balance unchanged
<br></br>
- [ ] Deposit/withdraw both use a confirm step before submitting, not a single blind submit
<br></br>
- [ ✅ ] Transfer to another person by name/search → money leaves your account, no way to see their account id
<br></br>
- [ ❓ ] Transfer to yourself / same account → rejected
    
    *The account doesn't show up in the "send to" dropdown, ¿which I guess is the same thing?*
<br></br>
- [ ✅ ] Transfer more than available balance → rejected, no partial transfer
- [ ✅ ] After any deposit/withdraw/transfer, the nav bar and Home page balance both update (no stale number) — `refreshAccounts()` check
- [ ✅ ] Transaction history loads, paginates (next/prev works, doesn't show duplicate or skipped rows across pages)
<br></br>
- [ ❌ ] Transaction history filter by type (deposit/withdrawal/transfer) works if present
    *Not present*
<br></br>
- [ ✅ ] Try to view another user's account by editing the URL's account id → 404, not the account's data, not a 403 that reveals it exists

---

## Tester C — Admin

Covers: `Admin.jsx`, `AdminAccountRow.jsx`, `AdminAuditLog.jsx`, `UserSearch.jsx`,
plus the admin/customer boundary.

- [ ] Log in as a non-admin → `/admin` is inaccessible (not just hidden nav, actually blocked)
- [ ] Log in as admin → nav bar turns red (admin theme), account/transfer tabs are hidden
- [ ] Admin sees list of all users and all accounts
- [ ] Freeze an account with a reason ≥ 10 characters → account shows frozen, customer can no longer deposit/withdraw/transfer on it
- [ ] Freeze attempt with a reason < 10 characters (or missing) → rejected
- [ ] Unfreeze an account → customer can transact again
- [ ] Adjust a balance as admin → posts a normal ledger entry (check transaction history for it), balance changes accordingly
- [ ] Try to open an account with the admin as owner (or self-adjust as a normal path) → refused, admins hold no accounts
- [ ] Search for a person to view/manage → results exclude the admin themself, query under 2 characters returns nothing
- [ ] `GET /api/admin/reconciliation` (open directly or via a page) reads `balanced: true` after the above actions
- [ ] Audit log shows the freeze/unfreeze/adjust actions just performed, with reasons

---

## Tester D — Cross-cutting: money display, accessibility, edge states

Runs across *every* page above — do this pass after A/B/C have exercised the
flows once, so there's data (frozen accounts, recent transactions) to look at.

- [ ] Every dollar amount on screen is formatted from cents correctly (spot check: seed accounts 9 and 18 — a five-digit balance next to a one-cent one should still line up)
- [ ] No page does arithmetic on a balance in the browser — it always reflects a fresh server response after an action
- [ ] Credits/debits are distinguished by a sign or word (e.g. "+", "-", "DEPOSIT"), never colour alone
- [ ] Every form field with an error has the error tied to it (visually and via `aria-describedby` if implemented) — not just a red border
- [ ] Tab through a full flow (login → deposit → logout) using only the keyboard — no dead ends, no invisible focus
- [ ] Focus outline is never suppressed anywhere (check buttons, links, inputs)
- [ ] Submit buttons disable / show a loading state while a request is in flight (try on slow network via devtools throttling) — no double-submit possible by clicking twice
- [ ] Empty states: brand-new user with no accounts, an account with no transactions yet
- [ ] Error states: server down (stop `python server.py` and try an action), invalid input, expired session
- [ ] 404 page appears for a nonsense route (`/whatever`), not a blank screen
- [ ] Resize to a small/mobile width — nothing overlaps or overflows unreadably
- [ ] Screenshot each page in a normal, error, and empty state (submission requirement, per AGENTS.md TODO)
