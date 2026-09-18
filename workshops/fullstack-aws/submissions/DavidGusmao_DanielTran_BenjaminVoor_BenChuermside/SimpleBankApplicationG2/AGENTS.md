# AGENTS.md

Shared context and the running TODO list. Read this before starting work, human
or AI. If something here is out of date, fix it in the same commit as the code
that made it out of date.

## Project values

**Brevity outranks everything else here.** This is a practice project, not a
production system, and it is graded partly on whether we can explain it. A
feature nobody on the team can walk a room through is worse than no feature.

- Scope stays small: 3-5 core features in the working plan, no more.
- Most documents stay under 300 words, so they can be explained in a short
  presentation. This file is the exception - it is a working log, not a
  presentation artifact.
- Prefer clarity over completeness. If a feature cannot be explained simply, it
  probably should not be added.
- Before adding anything, ask whether it earns the lines it costs.

---

## Where we are

| Layer | State |
| --- | --- |
| Domain, services, repository | Done. 168 tests, 16 skip without a Mongo cluster. |
| REST API | Done. 19 routes, `bank/api.py`. Contract in `APIDocs.txt`. |
| Auth | Done. Register, login, `/api/auth/me`, stored tokens, ADMIN role. |
| Database | Done for MongoDB Atlas. In-memory fallback. **MySQL not started.** |
| Frontend | Every screen in brief §7 is built. Routing, auth, API layer, credit accounts, pay-a-person, and the admin console. No stubs left. |

Run it: `python server.py` in one terminal, `cd frontend && npm run dev` in
another. Seed login `aaron.forrester@example.com`, password `BankDemo123!`.

---

## TODO

### Must ship — these are graded

- [x] **Decide what happens to `TransactionMenu.jsx`.** Settled: it is the
      shared form. `Deposit.jsx` and `Withdraw.jsx` render it with `fixedKind`,
      so the three actions share one set of money rules.
- [x] **Frontend pages.** All six screens in brief §7 exist, plus transfer,
      profile and admin.
- [ ] **SQL script.** A submission requirement and it does not exist in the repo.
      The schema and inserts are written and verified in the team's
      `seed_data_bank_app.md` planning doc, §3–4. Extract to `sql/schema.sql`
      and `sql/seed.sql`. Its amounts are `DECIMAL`; ours are integer cents, so
      decide which the script reflects and say so in a comment.
- [ ] **UI screenshots.** A submission requirement. Capture per feature as it
      lands, including error and empty states, not just the happy path.
- [ ] **Decide MySQL or MongoDB.** Open since day one. It changes what the SQL
      script above actually is. Ask the instructor; do not guess.

### Should ship

- [x] **Confirm step on deposit and withdraw.** WCAG 3.3.4 asks that a money
      transaction be reversible, checked, or confirmed. Done as
      `components/ConfirmTransaction.jsx`, rendered by `TransactionMenu.jsx`
      and `Transfer.jsx` - two states in one component, not a second page.
- [ ] **Validation messages on the UI.** On the brief's bonus list. Errors tied
      to their field with `aria-describedby`, never signalled by border colour
      alone.
- [ ] **Empty and loading states** on every page that fetches.

### Stretch — only after the above are demoable

- [ ] **AI assistant.** Read-only,
      three tools, session-scoped. Behind a flag so an unfinished one is switched
      off and the demo is unaffected.
- [ ] **Deployment**, if the program expects it. Unconfirmed.

### Deliberately not doing

Refresh tokens, httpOnly cookie sessions, rate limiting on login, and a second
account-type minimum balance. All are the right end state and none is graded.
They are listed under "Not done yet" in the README.

---

## Conventions that will bite you

**Money is an integer number of cents.** `123456` is `1,234.56`. The API refuses
`25.00` and `"2500"` with a 400 rather than guessing, because guessing wrong is a
hundredfold error. In the frontend: `parseDollars` on the way in, `formatCents`
on the way out, cents in state, no arithmetic on dollars.

**Never compute a balance in the browser.** Every write endpoint returns the new
authoritative account beside the transaction. Render that.

**Ownership is checked server-side on every account-scoped route**, and an
account belonging to someone else reads as 404, not 403. Do not add a route that
takes an account id without going through `service.get_account_for`.

**An admin holds no accounts.** The role is supervisory - freeze, adjust,
read the audit log - and every one of those powers is over somebody else's
money. An admin who also banked here could freeze their own account, adjust
their own balance and sign off on both, so `open_account` refuses an admin as
the owner and the nav hides the account and transfer tabs for them. Seed
accounts 8, 11 and 12 used to belong to the two admins and were moved to
customers rather than deleted, because the account numbers are positional and
`EXPECTED_BALANCES` keys off them.

**The ledger is append-only.** A correction is a new entry in the opposite
direction. If you ever write an update to a transaction, the design has gone
wrong. `GET /api/admin/reconciliation` is the running proof and should always
come back `balanced: true`.

**Send a `clientTxnId`** on deposit, withdraw and transfer — one
`crypto.randomUUID()` per submission attempt, so a double-click cannot move the
money twice.

**Call `refreshAccounts()` after moving money.** The account list lives in the
auth context because the nav bar and the home page both read it. A deposit,
withdrawal or transfer that does not refresh it leaves both showing the old
balance. `const { refreshAccounts } = useAuth()`.

**Admin role comes from `BANK_ADMIN_CODE`, checked server-side.** There is one
register form for everybody, with an optional team code on it. A matching code
creates an ADMIN; a wrong one is a 403 that creates nobody, which is what the
"are you sure?" dialog on that page reacts to. The code exists nowhere in the
frontend — grep the bundle and you will not find it — because a comparison
written in JavaScript ships to the browser and stops nobody. See `api._role_for`.

**Tokens are signed JWTs, and the `role` claim is not what authorizes.** A token
is `header.payload.signature`; the payload carries `sub`, `username`, `name`,
`role`, `iat` and `exp`, and is readable by anyone holding it — base64 is not
encryption, so nothing sensitive goes in there. `read_token` checks the signature
*before* it parses anything, then the expiry.

The claim you must not trust is `role`. It is signed, so it has not been
tampered with, but a JWT cannot be recalled and ours last a week, so a user
demoted after logging in still carries a token saying ADMIN. `api._authenticate`
therefore re-reads the `User` from storage and authorizes on the stored role.
**Never authorize off `claims["role"]`.**

There is no tokens table — signing replaced storing, so there is nothing to
revoke and `BANK_SECRET` is load-bearing again. **You do not need to set it:**
`server.py` generates one on first run and saves it to your gitignored `.env`, so
tokens survive restarts out of the box. Yours is personal — do not paste it into
the group chat and do not commit it. Only a deployed shared backend would need a
fixed agreed key, and it would set the variable in its own environment.

**A 401 ends the session, and only `lib/api.js` decides that.** Any 401 from any
call clears the stored token and drops `user`, so the route guard sends you to
the sign-in form — a token that stopped being accepted must not leave the UI
claiming you are signed in while every request fails. Login and register are
exempt, because a 401 there means "wrong password", not "your session ended". Do
not add per-page 401 handling; it is done once in `request()`.

**Account numbers stay out of the interface.** They are database keys. A
transfer names a *person* (`toUserId`) and the server resolves it to their
primary account, so the browser is never told anyone else's account ids. The id
still lives in the URL, which is fine - it is checked for ownership on every
request.

**All backend code is standard library only.** `requirements.txt` exists for
pymongo and nothing else. Keep it that way.

---

## Where things are

| Path | What |
| --- | --- |
| `bank/` | The backend. `api.py` has the route table; `services.py` has the rules. |
| `APIDocs.txt` | The API contract. The frontend's source of truth. |
| `frontend/` | React + Vite. Every screen in brief §7. |
| `test_*.py` | 168 tests. `python -m unittest -q`. |
| `tools/check_mongo.py` | Run when Atlas will not connect. It explains what failed. |
