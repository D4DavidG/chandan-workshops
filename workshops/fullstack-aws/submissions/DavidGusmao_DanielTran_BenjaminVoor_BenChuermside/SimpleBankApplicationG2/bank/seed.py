"""Demo data: the cohort roster from `seed_data_bank_app.md`, in Python.

WHY REPLAY INSTEAD OF ASSIGN
---------------------------
The obvious way to seed is to set each balance to its final figure and insert the
ledger rows next to it. This module does not do that. It opens each account at
zero and then replays its transactions through `BankService.deposit` and
`.withdraw` - the same methods an HTTP request reaches.

That costs a few milliseconds and buys three things:

  1. Reconciliation is true by construction. There is no path here that can move
     a balance without writing the matching entry, because there is no path here
     that touches a balance at all.
  2. Loading the seed is itself a test. If a rule is broken, seeding raises
     instead of quietly producing a database that disagrees with the code.
  3. The resulting balances are a genuine prediction. Every figure in the seed
     document was computed independently; if replaying the same ledger through
     this codebase produces those exact numbers, the arithmetic agrees. The check
     at the bottom of this file asserts precisely that.

WHAT THE NUMBERS ARE FOR
------------------------
Several balances are chosen to break something on purpose, and they should not be
tidied up. The seed document explains each one; the short version:

    account  4   0.00        empty state, and a withdrawal against exactly zero
    account  6   12.50       overdraft rejection: try to withdraw 12.51
    account  9   84,210.75   thousands separators and tabular-nums alignment
    account 10   FROZEN      every deposit and withdrawal must be rejected
    account 11   1,234.56    built from 1000.10 + 234.20 + 0.30 - 0.04, which
                             drifts to 1234.5599999999999 in IEEE 754
    account 18   0.01        one cent: rounding and truncation in display code

Accounts 9, 13 and 20 turned out to drift under float arithmetic too, which was
found by accident while verifying the seed file rather than designed in.

PASSWORDS AND EMAILS
--------------------
Every seeded user has the password `BankDemo123!`. That is fine for a demo and
only for a demo. Every address is on `example.com`, which RFC 2606 reserves for
exactly this and which can never receive mail - no real address belongs in a file
that ends up in a public repository.
"""
from .models import ROLE_ADMIN
from .money import format_money
from .security import hash_password

# The shared demo password. Hashed on the way in by `register_user`; the
# plaintext exists here, in the demo seed, and nowhere else.
DEMO_PASSWORD = "BankDemo123!"

# (name, email, role). Order fixes the user ids, 1 to 14.
#
# Four names in the source roster were derived from handles and are unconfirmed
# (Ayan Shabbir, Benjamin Voor, Bianca Alvarado, Justin Lin). Confirm them with
# their owners before the demo, or use the handle as the display name.
USERS = [
    ("Aaron Forrester",   "aaron.forrester@example.com",   "CUSTOMER"),
    ("Alexander Melendez", "alexander.melendez@example.com", "CUSTOMER"),
    ("Alisa Katsionova",  "alisa.katsionova@example.com",  "CUSTOMER"),
    ("Ayan Shabbir",      "ayan.shabbir@example.com",      "CUSTOMER"),
    ("Benjamin Voor",     "benjamin.voor@example.com",     "CUSTOMER"),
    ("Bianca Alvarado",   "bianca.alvarado@example.com",   ROLE_ADMIN),
    ("Daniel Tran",       "daniel.tran@example.com",       "CUSTOMER"),
    ("David Gusmao",      "david.gusmao@example.com",      ROLE_ADMIN),
    ("Erik Mayes",        "erik.mayes@example.com",        "CUSTOMER"),
    ("Justin Lin",        "justin.lin@example.com",        "CUSTOMER"),
    ("Paul Bobev",        "paul.bobev@example.com",        "CUSTOMER"),
    ("Sean Cook",         "sean.cook@example.com",         "CUSTOMER"),
    ("Shraeyas Muthaiah", "shraeyas.muthaiah@example.com", "CUSTOMER"),
    ("Sonia Jain",        "sonia.jain@example.com",        "CUSTOMER"),
]

# (owner user id, account type, freeze after seeding?). Order fixes account ids 1-20.
ACCOUNTS = [
    (1, "CHECKING", False), (1, "SAVINGS", False),
    (2, "CHECKING", False),
    (3, "CHECKING", False), (3, "SAVINGS", False),
    (4, "CHECKING", False),
    (5, "CHECKING", False),
    # Accounts 8, 11 and 12 used to belong to users 6 and 8, who are the two
    # admins. An admin does not hold an account (see BankService.open_account),
    # so they were moved to customers rather than deleted: the ids are positional
    # and EXPECTED_BALANCES, the ledger below and the docs all key off them.
    (5, "CHECKING", False),                           # account 8, was user 6
    (7, "CHECKING", False), (7, "SAVINGS", True),     # account 10 ends up FROZEN
    (9, "CHECKING", False),                           # account 11, was user 8
    (10, "SAVINGS", False),                           # account 12, was user 8
    (9, "CHECKING", False),
    (10, "CHECKING", False),
    (11, "CHECKING", False),
    (12, "CHECKING", False),
    (13, "CHECKING", False), (13, "SAVINGS", False),
    (14, "CHECKING", False), (14, "SAVINGS", False),
]

# (account id, "D" deposit or "W" withdrawal, amount in cents). Amounts are ints,
# never floats - that is the whole point of the exercise and it starts at the
# data. 396800 is 3,968.00.
LEDGER = [
    (1, "D", 396800), (1, "W", 49104), (1, "W", 43152), (1, "W", 29760), (1, "W", 26784),
    (2, "D", 2520000), (2, "W", 179550), (2, "W", 56700), (2, "W", 708750),
    (3, "D", 145974), (3, "W", 1095), (3, "W", 40508), (3, "W", 7664), (3, "W", 5473),
    (4, "D", 25000), (4, "W", 25000),
    (5, "D", 688000), (5, "W", 74820), (5, "W", 183180),
    (6, "D", 1250),
    (7, "D", 588032), (7, "W", 66154), (7, "W", 26461), (7, "W", 127897),
    (8, "D", 80000), (8, "W", 5100), (8, "W", 24900),
    (9, "D", 13473720), (9, "W", 2172637), (9, "W", 202106), (9, "W", 1061055), (9, "W", 1616847),
    (10, "D", 192000), (10, "W", 7920), (10, "W", 7200), (10, "W", 16560), (10, "W", 40320),
    (11, "D", 100010), (11, "D", 23420), (11, "D", 30), (11, "W", 4),
    (12, "D", 3200000), (12, "W", 336000), (12, "W", 672000), (12, "W", 192000),
    (13, "D", 119358), (13, "W", 31779), (13, "W", 12980),
    (14, "D", 968000), (14, "W", 127050), (14, "W", 101640), (14, "W", 134310),
    (15, "D", 20491), (15, "W", 1614), (15, "W", 6070),
    (16, "D", 1599998), (16, "W", 341999), (16, "W", 24000), (16, "W", 24000), (16, "W", 210000),
    (17, "D", 49672), (17, "W", 7265), (17, "W", 5402), (17, "W", 5588), (17, "W", 372),
    (18, "D", 1),
    (19, "D", 844800), (19, "W", 107712), (19, "W", 69696), (19, "W", 139392),
    (20, "D", 11536), (20, "W", 3980), (20, "W", 346),
]

# The balances the seed document states, in cents, computed there independently
# of this codebase. Replaying LEDGER must reproduce them exactly.
EXPECTED_BALANCES = {
    1: 248000, 2: 1575000, 3: 91234, 4: 0, 5: 430000,
    6: 1250, 7: 367520, 8: 50000, 9: 8421075, 10: 120000,
    11: 123456, 12: 2000000, 13: 74599, 14: 605000, 15: 12807,
    16: 999999, 17: 31045, 18: 1, 19: 528000, 20: 7210,
}

FREEZE_REASON = "Seeded frozen for the freeze/unfreeze demo path"


def load(service, password: str = DEMO_PASSWORD, verify: bool = True) -> dict:
    """Populate an empty store. Returns a summary for the caller to print.

    Expects a store with nothing in it: ids are positional, so seeding twice
    produces users 15 to 28 and the account numbers stop matching the document.
    """
    if service.store.all_users():
        raise RuntimeError("seed.load() expects an empty store")

    # --- users -----------------------------------------------------------
    # Hash the shared demo password ONCE and reuse it for all fourteen rows.
    # PBKDF2 at 600,000 rounds costs about 0.6 seconds on purpose, so hashing per
    # user would put nine seconds on every server start for no security benefit:
    # the password is identical and published in this file either way. The SQL
    # seed script does the same thing with one bcrypt hash.
    #
    # This is a demo shortcut and nothing else. Real registration goes through
    # `register_user(password=...)`, which salts each user separately.
    shared_hash = hash_password(password)
    users = {}
    for name, email, role in USERS:
        user = service.register_user(name, email, role=role,
                                     password_hash=shared_hash)
        users[user.user_id] = user

    # --- accounts, opened at zero ----------------------------------------
    # Opening balance stays 0 deliberately. Every cent arrives as a ledger
    # entry below, so there is no "where did this money come from" gap.
    accounts = {}
    to_freeze = []
    for owner_id, account_type, freeze in ACCOUNTS:
        account = service.open_account(users[owner_id], account_type)
        accounts[account.account_id] = account
        if freeze:
            to_freeze.append(account.account_id)

    # --- ledger, replayed through the real rules --------------------------
    # Each entry carries the same client_txn_id as the SQL seed, which also
    # populates the idempotency index: resubmitting "seed-0001-01" is refused.
    admin = next(u for u in users.values() if u.is_admin)
    for index, (account_id, direction, amount) in enumerate(LEDGER, start=1):
        account = accounts[account_id]
        actor = users[account.user_id]
        client_txn_id = f"seed-{index:04d}-{account_id:02d}"
        if direction == "D":
            service.deposit(account_id, amount, actor, client_txn_id)
        else:
            service.withdraw(account_id, amount, actor, client_txn_id)

    # --- freeze last -------------------------------------------------------
    # After the replay, not before: a frozen account rejects movement, which is
    # exactly the rule that would stop its own ledger from loading.
    for account_id in to_freeze:
        service.set_frozen(account_id, True, FREEZE_REASON, admin)

    if verify:
        _verify(service)

    return {
        "users": len(users),
        "accounts": len(accounts),
        "transactions": len(LEDGER),
        "password": password,
        "admins": [u.email for u in users.values() if u.is_admin],
    }


def _verify(service) -> None:
    """Two assertions that make loading the seed a test rather than a fixture."""
    # 1. Every balance matches the figure computed independently in the seed doc.
    for account_id, expected in EXPECTED_BALANCES.items():
        actual = service.store.get_account(account_id).balance
        if actual != expected:
            raise AssertionError(
                f"account {account_id}: expected {format_money(expected)}, "
                f"replayed to {format_money(actual)}"
            )
    # 2. Every stored balance still equals the sum of its own ledger.
    broken = service.reconcile_all()
    if broken:
        raise AssertionError(f"seeded data does not reconcile: {broken}")
