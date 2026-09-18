# Simple Bank Application

A banking system with a REST API, authentication, an immutable ledger and an
admin console. Python backend (standard library only), React + Vite frontend,
optional MongoDB Atlas storage with an in-memory fallback.

Users register, open accounts, deposit, withdraw, transfer money to another
person and read their transaction history. Admins freeze accounts, post
correcting entries and read an audit log — they hold no accounts themselves.

- **Backend:** Python 3.10+, `http.server`, no framework, no third-party package.
- **Frontend:** React 19 + Vite, plain JavaScript, plain CSS, no UI library.
- **Storage:** in-memory by default; MongoDB Atlas when `.env` is configured.

---

## Quick start

**Prerequisites:** Python 3.10 or newer (the code uses `str | None` syntax) and
Node.js 18+ for the frontend. Nothing to `pip install` unless you want MongoDB.

### 1. The demo — no server, no setup

```bash
python demo.py           # walkthrough of every business rule
python demo.py --step    # pauses between sections, for presenting
```

Eleven sections. Sections 1–10 call service methods and print what each rule did;
section 11 reaches the same rules over HTTP so the rules and their status codes
appear side by side.

### 2. The API

```bash
python server.py         # http://127.0.0.1:8000
```

Flags: `--port 9000`, `--host 0.0.0.0`, `--empty` (no seed data),
`--memory` (ignore `.env` and run in memory), `--reset` (wipe your database and
reload the seed).

### 3. The frontend

In a second terminal, with the backend running:

```bash
cd frontend
npm install              # once
npm run dev              # http://localhost:5173
```

`npm run dev` proxies `/api` to `127.0.0.1:8000` (see `vite.config.js`), so the
browser sees one origin and there is nothing to configure. On a different backend
port:

```bash
VITE_API_TARGET=http://127.0.0.1:9000 npm run dev            # bash
$env:VITE_API_TARGET = "http://127.0.0.1:9000"; npm run dev  # PowerShell
```

Also `npm run build` (bundle into `dist/`) and `npm run lint` (oxlint, currently
clean — keep it that way).

### 4. Seed logins

Every seeded password is `BankDemo123!`.

| Role | Email |
| --- | --- |
| Customer | `aaron.forrester@example.com` |
| Admin | `david.gusmao@example.com`, `bianca.alvarado@example.com` |

The seed is 14 users, 20 accounts and 73 transactions, replayed through the real
service methods rather than assigned — so reconciliation is true by construction
and loading the seed is itself a test. Several balances break something on
purpose (account 4 is empty, 6 is nearly empty for overdraft rejection, 10 is
frozen, 18 holds one cent) and should not be tidied up.

### 5. Postman

Import `postman_collection.json`, run **Auth → Login (customer)**, then anything
else — the login request stores the token in a collection variable that every
other request sends. Regenerate it from the live route table with
`python tools/export_postman.py`.

---

## Architecture

Each layer depends only on the one below it. Nothing points back up.

```
Frontend (React)
     |
  api.py            Controller. HTTP in, JSON out. NO business rules.
     |
  serializers.py    Domain objects -> JSON. Money leaves as int cents.
     |
  services.py       Every business rule. NO HTTP, NO SQL, NO framework.
     |
  models.py         User, Account, Transaction. Plain Python classes.
     |
  store.py          Repository. In-memory, or mongo_store.py for Atlas.
```

`test_bank.py` exercises every business rule without importing `api.py` at all,
so the separation is checked rather than asserted. Swapping the database means
replacing `store.py` and nothing else.

### Repository layout

| Path | What |
| --- | --- |
| `bank/api.py` | The route table, token check, role check, error-to-status map. |
| `bank/services.py` | Every business rule. Takes a lock around anything that moves money. |
| `bank/models.py` | `User`, `Account`, `Transaction`. `Account.balance` has no setter. |
| `bank/money.py` | Money as integer cents. Read this first. |
| `bank/security.py` | PBKDF2-HMAC-SHA256 passwords, HS256 JSON Web Tokens. |
| `bank/store.py`, `bank/mongo_store.py` | In-memory and MongoDB repositories, same methods. |
| `bank/seed.py`, `bank/config.py`, `bank/errors.py`, `bank/serializers.py` | Demo data, `.env` reader, domain exceptions, JSON output. |
| `server.py` | Entry point. Composes store → service → API, seeds, serves. |
| `demo.py` | Console walkthrough of every rule, then the same rules over HTTP. |
| `frontend/src/lib/api.js` | One function per endpoint. **Nothing else calls `fetch`.** |
| `frontend/src/context/AuthContext.jsx` | Login, register, token storage, account list. |
| `frontend/src/pages/`, `frontend/src/components/` | One page per file; `App.jsx` has every route. |
| `APIDocs.txt` | The full API contract. The frontend's source of truth. |
| `tools/check_mongo.py` | Seven checks that this machine can use Atlas. |
| `AGENTS.md` | Current state, TODO list, conventions. Read before starting work. |

---

## The API

19 routes. `APIDocs.txt` is the full contract; this is the index.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/auth/register` | — | Create a user, return a token |
| `POST` | `/api/auth/login` | — | Exchange email + password for a token |
| `GET` `POST` | `/api/auth/me` | token | Read or edit your own profile |
| `GET` | `/api/health` | — | Liveness check |
| `POST` `GET` | `/api/accounts` | token | Open an account / list your accounts |
| `GET` | `/api/accounts/{id}` | token | Account details |
| `POST` | `/api/accounts/{id}/deposit` | token | Deposit |
| `POST` | `/api/accounts/{id}/withdraw` | token | Withdraw |
| `GET` | `/api/accounts/{id}/transactions` | token | History, paginated |
| `POST` | `/api/transfers` | token | Transfer to another person |
| `GET` | `/api/admin/users`, `/api/admin/accounts` | ADMIN | Everyone, everything |
| `POST` | `/api/admin/accounts/{id}/freeze` | ADMIN | Freeze or unfreeze, with a reason |
| `POST` | `/api/admin/accounts/{id}/adjust` | ADMIN | Post a correcting ledger entry |
| `GET` | `/api/admin/audit` | ADMIN | Who did what, to which account, and why |
| `GET` | `/api/admin/reconciliation` | ADMIN | Accounts where balance ≠ sum(ledger) |

Example — deposit `100.00` into account 1:

```http
POST /api/accounts/1/deposit
Authorization: Bearer <token>
Content-Type: application/json

{"amount": 10000, "clientTxnId": "a3f1-...-9c2e"}
```

The response carries the transaction **and the whole updated account**, so the
client never computes a balance itself.

---

## Rules that will bite you

**Money is an integer number of cents.** `123456` is `1,234.56`. The API refuses
`25.00` and `"2500"` with a 400 rather than guessing, because guessing wrong is a
hundredfold error. In the frontend: `parseDollars` on the way in, `formatCents`
on the way out, cents in state, no arithmetic on dollars.

**Never compute a balance in the browser.** Every write endpoint returns the new
authoritative account. Render that, and call `refreshAccounts()` afterwards so
the nav bar and home page do not keep showing the old number.

**Send a `clientTxnId`** on deposit, withdraw and transfer — one
`crypto.randomUUID()` per submission attempt, so a double-clicked button cannot
move the money twice.

**The ledger is append-only.** A correction is a new entry in the opposite
direction. There is no route that sets a balance and there should never be one;
`GET /api/admin/reconciliation` is the running proof and must stay `balanced`.

**Ownership is checked server-side on every account-scoped route**, and an
account belonging to someone else reads as 404, not 403. Account numbers stay out
of the interface — a transfer names a *person* and the server resolves their
account.

**Never authorize off the token's `role` claim.** It is signed, so it is not
forged, but tokens last a week and a demoted user still carries one saying ADMIN.
`api._authenticate` re-reads the user from storage and authorizes on that.

**A 401 ends the session, and only `lib/api.js` decides that.** Any 401 clears
the stored token and drops the user, so the route guard redirects to sign-in.
Login and register are exempt. Do not add per-page 401 handling.

**An admin holds no accounts.** The role is supervisory, and every one of its
powers is over somebody else's money.

---

## Configuration

Copy `.env.example` to `.env` (gitignored) — it documents every key. Nothing is
required to run.

| Key | Effect |
| --- | --- |
| `BANK_SECRET` | JWT signing key. **You do not need to set this** — `server.py` generates one on first run and appends it to your `.env`, so tokens survive a restart. Personal; never commit or share it. |
| `BANK_ADMIN_CODE` | Shared code that lets someone register as an ADMIN. Unset means admin registration is closed. Compared server-side only — it never reaches the browser. |
| `MONGODB_URI` | Atlas connection string. **Setting it is the switch** to MongoDB; there is no `--mongo` flag, and `--memory` is the way back. |
| `MONGODB_DB` | Which database in the cluster. Required whenever `MONGODB_URI` is set — the server refuses to start rather than guess. |

A real environment variable always wins over the file, so
`MONGODB_DB=simple_bank_scratch python server.py` overrides it for one run.

### Using MongoDB Atlas

1. `pip install -r requirements.txt` (pymongo, dnspython — the only third-party
   packages this project uses, and only for this path).
2. In Atlas: **Database Access → Add New Database User**. Username is your first
   name, lowercase. Click **Autogenerate Secure Password** and copy it — Atlas
   will not show it again, and an autogenerated alphanumeric password sidesteps
   the percent-encoding a connection string would otherwise need. Privileges:
   **Read and write to any database**.
3. **Database → Connect → Drivers → Python.** Take *only* the connection string.
   Ignore the version dropdown and the `pip install` line on that page. Replace
   `<db_password>`, angle brackets and all.
4. Put both keys in `.env`, no quotes, no spaces around the `=`:

   ```bash
   MONGODB_URI=mongodb+srv://david:YourPassword@cluster0.ab1cd.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0
   MONGODB_DB=simple_bank_david
   ```

5. `python tools/check_mongo.py`. Seven checks, each failing in a way you would
   otherwise spend an afternoon on: driver import, URI parsing, DNS on the `+srv`
   hostname, ping (**your IP not being on the access list is the usual one**),
   credentials, a read/write round-trip, and a real multi-document transaction —
   the last being the guarantee `transfer()` depends on. It writes only to a
   `_connection_check` collection and cleans up after itself.

One cluster, several databases: `simple_bank` is the shared demo data,
`simple_bank_<yourname>` is your own (**default to this**, so your reseed does
not delete what someone is demoing from), and `simple_bank_test` is wiped
constantly by the test suite. The seed loads automatically the first time your
database is empty, and only then; `--reset` starts over.

---

## Testing

```bash
python -m unittest -q                  # 168 tests, 16 skip without a cluster
MONGO_TESTS=1 python -m unittest -q    # including the Mongo suite
python -m unittest test_bank           # rules only, ~0.01 seconds
```

| Suite | Covers |
| --- | --- |
| `test_bank.py` | Business rules, called directly. Imports nothing HTTP. |
| `test_api.py` | Routing, auth, error mapping, serialization, the seed, and one end-to-end pass over a real socket. |
| `test_mongo.py` | A live cluster, opt-in with `MONGO_TESTS=1`. Always uses `simple_bank_test`, whatever `MONGODB_DB` says. |

Both non-Mongo suites assert `reconcile_all() == []` in `tearDown`, so the ledger
invariant is checked after every test rather than in one test of its own. Some
tests exist to make a specific mistake fail loudly — a route that sets a balance,
a route added without auth, a 404 that is distinguishable from a missing account.

Fixtures hash at 1,000 PBKDF2 rounds instead of 600,000, because a suite slow
enough to skip is a suite that gets skipped. The round count lives inside each
hash, so verification is unaffected, and a test guards the real default.

The frontend has no automated tests; `frontend/TESTING.md` is the manual
checklist to run before a demo.

---

## Not done yet

- **MySQL.** The brief says MySQL "to be confirmed" while the syllabus teaches
  MongoDB. Atlas being set up unblocks the Mongo path; it does not settle the
  grading question. The SQL schema and seed script are still owed.
- **UI screenshots** for submission.
- **Deliberately skipped:** refresh tokens, httpOnly cookie sessions, login rate
  limiting. All are the right end state; none is graded.

`http.server` is single-threaded and is not a production server. It is the right
choice here because it ships with Python, which is what keeps the backend
installable with zero setup.
