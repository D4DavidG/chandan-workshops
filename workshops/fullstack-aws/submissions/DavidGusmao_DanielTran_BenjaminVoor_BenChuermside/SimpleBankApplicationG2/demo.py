"""Console walkthrough of the whole backend. Run with: python demo.py

    python demo.py              # run straight through, in memory
    python demo.py --step       # pause at each section: for presenting
    python demo.py --mongo      # run against MongoDB Atlas instead of memory
    python demo.py --step --mongo

Sections 1 to 10 exercise every rule in `services.py` by calling methods, and
print what happened. Section 11 then reaches the same rules through the REST
layer, so the same behaviour is visible as HTTP status codes. Section 12 appears
only with --mongo, and shows the one thing memory cannot: the records are still
there, read back through a second connection.

No typing required and no server needed, so it is safe to run during a demo
without typing under pressure or hoping a port is free.

--step is for presenting to a room. It stops before each section and waits for
Enter, so the narration happens between sections instead of racing a wall of
scrolling output.

--mongo uses its own database, `simple_bank_demo`, and wipes it on the way in.
Never the shared `simple_bank`, and never your own working database: a demo that
may need running twice has to survive being run twice, and one that deletes the
data somebody else is about to present is worse than no demo.
"""
import argparse
import json
import os

from bank import (
    AccountNotActive, AccountNotFound, BankAPI, BankError, BankService, BankStore,
    DuplicateTransaction, InsufficientFunds, InvalidAmount, NotAuthorized,
    format_money, issue_token,
)

# The database --mongo uses. Deliberately not `simple_bank` (the shared demo
# data) and not `simple_bank_<yourname>` (whatever you are working against).
DEMO_DB = "simple_bank_demo"

STEP = False


def pause():
    """Wait for Enter between sections, under --step."""
    if not STEP:
        return
    try:
        input("\n        ... Enter for the next section (Ctrl+C to stop) ")
    except (EOFError, KeyboardInterrupt):
        print("\n  stopped.")
        raise SystemExit(0)


def rule(label):
    pause()
    print(f"\n{'=' * 68}\n{label}\n{'=' * 68}")


def ok(msg):
    print(f"  [ok]       {msg}")


def blocked(exc):
    print(f"  [blocked]  {type(exc).__name__}: {exc}")


def attempt(label, fn):
    """Run something expected to fail and report which rule stopped it."""
    print(f"  attempting: {label}")
    try:
        fn()
        print("  [PROBLEM]  that should not have been allowed")
    except BankError as exc:
        blocked(exc)
    except (ValueError, TypeError) as exc:
        blocked(exc)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Console walkthrough of the backend")
    p.add_argument("--step", action="store_true",
                   help="pause before each section and wait for Enter")
    p.add_argument("--mongo", action="store_true",
                   help=f"run against MongoDB (database {DEMO_DB!r}) instead of memory")
    return p


def open_store(args):
    """The store this run uses, and a line describing it for the banner."""
    if not args.mongo:
        return BankStore(), "in memory (nothing here is saved)"

    from bank import config
    config.load_env()
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        print("  --mongo needs MONGODB_URI in .env. See the README, or run:")
        print("      python tools/check_mongo.py")
        raise SystemExit(1)
    try:
        from bank.mongo_store import MongoStore
    except ImportError:
        print("  --mongo needs pymongo:  python -m pip install -r requirements.txt")
        raise SystemExit(1)

    store = MongoStore(uri, DEMO_DB)
    # Wipe first, so the walkthrough survives being run twice. Without this the
    # second run dies registering Aaron, whose email is already taken - which is
    # the duplicate-email rule working correctly, and a terrible way to find out.
    store.reset()
    return store, f"MongoDB Atlas, database {DEMO_DB!r} (wiped on the way in)"


def main(argv=None):
    global STEP
    args = build_parser().parse_args(argv)
    STEP = args.step

    store, storage = open_store(args)
    svc = BankService(store)

    print("=" * 68)
    print("  Simple Bank Application: backend walkthrough")
    print("=" * 68)
    print(f"  storage: {storage}")
    if STEP:
        print("  --step is on: press Enter to advance through each section.")

    rule("1. Users and accounts")
    aaron = svc.register_user("Aaron Forrester", "aaron.forrester@example.com")
    erik = svc.register_user("Erik Mayes", "erik.mayes@example.com")
    david = svc.register_user("David Gusmao", "david.gusmao@example.com", role="ADMIN")
    ok(f"registered {aaron}")
    ok(f"registered {erik}")
    ok(f"registered {david}  (role: {david.role})")

    checking = svc.open_account(aaron, "CHECKING", 1250)
    savings = svc.open_account(aaron, "SAVINGS", 50000)
    erik_acct = svc.open_account(erik, "CHECKING", 8421075)
    for acct in (checking, savings, erik_acct):
        ok(str(acct))

    attempt("register a second user with Aaron's email",
            lambda: svc.register_user("Impostor", "AARON.FORRESTER@example.com"))

    rule("2. Deposits and withdrawals")
    svc.deposit(checking.account_id, 10000, aaron)
    ok(f"deposited 100.00, balance now {format_money(checking.balance)}")
    svc.withdraw(checking.account_id, 1250, aaron)
    ok(f"withdrew 12.50, balance now {format_money(checking.balance)}")

    attempt("withdraw 999.00 from a balance of 100.00",
            lambda: svc.withdraw(checking.account_id, 99900, aaron))
    attempt("deposit a negative amount",
            lambda: svc.deposit(checking.account_id, -5000, aaron))
    attempt("deposit zero",
            lambda: svc.deposit(checking.account_id, 0, aaron))
    attempt('deposit "50.00" as a dollars-and-cents string',
            lambda: svc.deposit(checking.account_id, "50.00", aaron))
    attempt("deposit a float instead of an int",
            lambda: svc.deposit(checking.account_id, 10.50, aaron))

    rule("3. The account type decides what may leave (polymorphism, not an if)")
    # Read the limit off the account instead of writing a number here. This
    # section used to hardcode 475.01 against a 25.00 savings minimum; the
    # minimum is 0 now, and the demo keeps working because it asks the object the
    # same question `services.py` asks.
    available = savings.available_for_withdrawal()
    ok(f"savings balance {format_money(savings.balance)}, "
       f"minimum {format_money(savings.minimum_balance)}, "
       f"available {format_money(available)}")
    over = available + 1
    attempt(f"withdraw {format_money(over)}, one cent past what may leave",
            lambda: svc.withdraw(savings.account_id, over, aaron))
    svc.withdraw(savings.account_id, available, aaron)
    ok(f"withdrew {format_money(available)}, balance now "
       f"{format_money(savings.balance)} (at the minimum)")
    print("     note: services.py never checks the account type. It calls")
    print("     account.can_withdraw(), and the subclass supplies the rule.")
    print("     Both types hold 0.00 today, so nothing is held back - the point")
    print("     is that raising the minimum needs no change in services.py.")

    rule("4. Precision: money is a whole number of cents")
    # Account 20 from the seed file: one deposit and two withdrawals that come to
    # exactly 7210 cents in integers, and 72.10000000000001 in float.
    precise = svc.open_account(aaron, "CHECKING")
    svc.deposit(precise.account_id, 11536, aaron)
    for amount in [3980, 346]:
        svc.withdraw(precise.account_id, amount, aaron)
    drift = 115.36 - 39.80 - 3.46
    ok("115.36 - 39.80 - 3.46, done as 11536 - 3980 - 346")
    ok(f"  cents   : {precise.balance}  ->  {format_money(precise.balance)}")
    print(f"  [float] : {drift!r}   <- what the same arithmetic gives in float")
    print("     note: the integer answer is not rounded to look right. It is the")
    print("     only answer integer subtraction can produce.")

    rule("5. Idempotency: the double-clicked submit button")
    before = checking.balance
    svc.deposit(checking.account_id, 2500, aaron, client_txn_id="submit-0001")
    ok(f"first submit applied, balance {format_money(checking.balance)}")
    attempt("the same submission again (same client_txn_id)",
            lambda: svc.deposit(checking.account_id, 2500, aaron,
                                client_txn_id="submit-0001"))
    ok(f"balance unchanged at {format_money(checking.balance)} "
       f"(was {format_money(before)} before the first)")

    rule("6. Ownership: a user may not touch another user's account")
    print(f"  Erik's account is #{erik_acct.account_id}, holding "
          f"{format_money(erik_acct.balance)}")
    attempt("Aaron reads Erik's account",
            lambda: svc.get_account_for(erik_acct.account_id, aaron))
    attempt("Aaron withdraws from Erik's account",
            lambda: svc.withdraw(erik_acct.account_id, 100000, aaron))
    attempt("Aaron reads an account id that does not exist at all",
            lambda: svc.get_account_for(99999, aaron))
    print("     note: identical error for 'not yours' and 'does not exist'.")
    print("     A different message would confirm the account is real.")

    admin_view = svc.get_account_for(erik_acct.account_id, david)
    ok(f"admin may read it: {admin_view}")

    rule("7. Admin actions require the role, a reason, and a ledger entry")
    attempt("Aaron freezes an account",
            lambda: svc.set_frozen(erik_acct.account_id, True, "because I felt like it", aaron))
    attempt("admin adjusts with a one-word reason",
            lambda: svc.adjust(checking.account_id, 5000, "CREDIT", "oops", david))

    svc.adjust(checking.account_id, 5000, "CREDIT",
               "Reversing a fee misposted on 2026-09-10", david)
    ok(f"admin credited 50.00, balance now {format_money(checking.balance)}")
    ok(f"audit trail: {svc.audit[-1]}")
    print("     note: there is no set_balance method anywhere. Adjustments post a")
    print("     ledger entry, so balance == sum(ledger) still holds afterwards.")

    svc.set_frozen(erik_acct.account_id, True, "Suspected card compromise, under review", david)
    ok(f"admin froze account #{erik_acct.account_id}")
    attempt("Erik deposits into his own frozen account",
            lambda: svc.deposit(erik_acct.account_id, 1000, erik))

    rule("8. Transfer between accounts")
    svc.set_frozen(erik_acct.account_id, False, "Review complete, no fraud found", david)
    svc.transfer(checking.account_id, erik_acct.account_id, 2500, aaron)
    ok(f"Aaron sent 25.00 to Erik")
    ok(f"  Aaron  {format_money(checking.balance)}")
    ok(f"  Erik   {format_money(erik_acct.balance)}")
    attempt("transfer more than is available",
            lambda: svc.transfer(checking.account_id, erik_acct.account_id, 9999900, aaron))

    rule("9. Transaction history")
    rows, total = svc.history(checking.account_id, aaron, page=1, page_size=5)
    print(f"  account #{checking.account_id}, {total} entries, showing the most recent 5:")
    for txn in rows:
        print(f"    {txn}")

    rule("10. Reconciliation: balance must equal the sum of the ledger")
    for account in store.all_accounts():
        stored, ledger = svc.reconcile(account.account_id)
        mark = "ok " if stored == ledger else "BAD"
        print(f"  [{mark}] account #{account.account_id:<3} "
              f"balance {format_money(stored):>13}   ledger {format_money(ledger):>13}")

    broken = svc.reconcile_all()
    print()
    if broken:
        print(f"  RECONCILIATION FAILED for {len(broken)} account(s): {broken}")
    else:
        print(f"  All {len(store.all_accounts())} accounts reconcile. "
              f"Every balance change has a matching ledger entry.")

    api_section(svc, aaron, david, checking, erik_acct)

    if args.mongo:
        persistence_section(store, checking.account_id)

    if hasattr(store, "close"):
        store.close()


def persistence_section(store, account_id):
    """The one thing memory cannot show: the records outlived the objects.

    Everything above this point is also true of the in-memory store. What is only
    true here is that the balances exist somewhere other than this process, so
    this opens a SECOND connection and reads them back. Asking the store we have
    been using all along would prove nothing - it has the answers in hand.
    """
    rule("12. It is actually in the database")

    from bank.mongo_store import MongoStore
    other = MongoStore(os.environ["MONGODB_URI"], DEMO_DB)
    try:
        print("  opened a second, independent connection to the same database\n")
        account = other.get_account(account_id)
        ok(f"account #{account_id} reads back as {format_money(account.balance)}")
        ok(f"ledger sum over the same account: "
           f"{format_money(other.ledger_sum(account_id))}")
        ok(f"{len(other.all_users())} users and {len(other.all_accounts())} accounts "
           f"are stored")

        entries = other.audit_entries()
        ok(f"{len(entries)} admin action(s) in the audit log, which also survives:")
        for entry in entries:
            print(f"             {entry}")

        print()
        print("     none of these numbers came from the objects this script built.")
        print("     They were read out of Atlas by a connection that has never")
        print("     seen them. Stop this script, run it again without --mongo,")
        print("     and section 10 still reconciles - but nothing persists.")
    finally:
        other.close()


def api_section(svc, aaron, david, checking, erik_acct):
    """The same rules, reached over the REST layer instead of by calling methods.

    Calls `BankAPI.handle` directly rather than starting a server, so this runs
    in-process with no port and nothing to clean up. The point is the right-hand
    column: every rule demonstrated above now arrives as an HTTP status code, and
    that mapping lives in one table (`ERROR_STATUS` in bank/api.py) rather than
    scattered through the handlers.
    """
    rule("11. The same rules over HTTP")

    api = BankAPI(svc, secret="demo-secret-not-used-anywhere-real")

    def call(label, method, path, body=None, actor=None, expect=None):
        headers = {}
        if actor is not None:
            token = issue_token(actor.user_id, actor.email, actor.role, api.secret,
                                name=actor.name)
            headers["authorization"] = f"Bearer {token}"
        raw = json.dumps(body).encode("utf-8") if body else b""
        status, payload = api.handle(method, path, raw, headers)
        mark = "ok " if expect is None or status == expect else "BAD"
        detail = payload.get("error") or _summarise(payload)
        print(f"  [{mark}] {status}  {method:<5} {path:<42} {label}")
        if detail:
            print(f"          {detail}")

    print("  Aaron is logged in. Every call below carries his token.\n")
    call("his own account", "GET", f"/api/accounts/{checking.account_id}",
         actor=aaron, expect=200)
    call("deposit 10.00", "POST", f"/api/accounts/{checking.account_id}/deposit",
         {"amount": 1000}, aaron, expect=201)
    call("amount as a fractional JSON number", "POST",
         f"/api/accounts/{checking.account_id}/deposit", {"amount": 10.50}, aaron,
         expect=400)
    call('amount as a "10.50" string', "POST",
         f"/api/accounts/{checking.account_id}/deposit", {"amount": "10.50"}, aaron,
         expect=400)
    call("withdraw more than he has", "POST",
         f"/api/accounts/{checking.account_id}/withdraw", {"amount": 99999900},
         aaron, expect=409)
    call("ERIK'S account, by guessing the id", "GET",
         f"/api/accounts/{erik_acct.account_id}", actor=aaron, expect=404)
    call("an account that does not exist", "GET", "/api/accounts/99999",
         actor=aaron, expect=404)
    call("an admin-only route", "GET", "/api/admin/users", actor=aaron, expect=403)
    call("no token at all", "GET", "/api/accounts", expect=401)

    print("\n  The same two requests as an admin:\n")
    call("admin reads Erik's account", "GET",
         f"/api/accounts/{erik_acct.account_id}", actor=david, expect=200)
    call("admin lists every user", "GET", "/api/admin/users", actor=david, expect=200)

    print("\n     note the two 404s. 'not yours' and 'does not exist' are")
    print("     indistinguishable from outside, on purpose: a 403 on the first")
    print("     would confirm the account is real.")


def _summarise(payload: dict) -> str:
    """One short line about a successful response, for the demo output."""
    if "account" in payload:
        account = payload["account"]
        # The API sends cents; format for the human reading the demo output.
        return (f"balance {format_money(account['balance'])}, "
                f"{account['accountType']}, {account['status']}")
    if "users" in payload:
        return f"{len(payload['users'])} users"
    return ""


if __name__ == "__main__":
    main()
