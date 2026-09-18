"""Service layer. Every business rule lives here and nowhere else.

The brief lists three rules:

    - cannot withdraw more than balance
    - deposit amount must be positive
    - maintain a transaction record for each deposit and withdraw

Those are correct and incomplete. The rules actually enforced below:

    1. Deposit and withdrawal amounts are positive, at most 2 decimal places,
       and below a per-transaction ceiling.               (parse_amount)
    2. A withdrawal may not exceed what is *available*, which is the balance
       minus any minimum the account type requires.       (polymorphic)
    3. Frozen accounts reject all customer-initiated movement.
    4. Every balance change writes exactly one ledger entry, always.
    5. A resubmitted client transaction id is rejected rather than applied twice.
    6. A user may only touch their own accounts. Admins may read any account,
       but may not move money in one: that is what adjust() is for.
    7. Admins adjust by posting a ledger entry with a reason. Never by setting
       a balance.

Rules 3 through 7 are not in the brief. They are cheap now and painful to retrofit.

Sessions are deliberately not a rule here. A JWT is signed and carries its own
claims, so issuing and validating one needs the signing secret and no storage at
all - which makes it the controller's job, not a business rule. See
`bank/security.py` and `api.BankAPI._authenticate`.

No imports from any web framework or database library. The whole module can be
exercised by calling functions, which is what makes the tests fast and is what
"clean separation" has to mean in practice.
"""
from .errors import (
    AccountNotActive, AccountNotFound, DuplicateTransaction,
    InsufficientFunds, NotAuthorized,
)
from .models import (
    ACTIVE, DEPOSIT, FROZEN, ROLE_ADMIN, TRANSFER_IN, TRANSFER_OUT, WITHDRAWAL,
    Account, Transaction, User, make_account,
)
from .money import parse_amount
from .security import hash_password, verify_password


class BankService:
    """Holds the rules. Constructed with a store, and knows nothing else.

    Note what is NOT injected here: no request object, no database connection, no
    framework. Everything this class needs arrives as an argument. That is what
    lets `test_bank.py` exercise every rule with a plain function call, and it is
    what "clean MVC separation" has to mean in practice rather than as a diagram.

    Every method that changes data runs inside `self.store.atomic()`. The HTTP
    server is threaded, so two requests really can run at once, and the natural
    "read the balance, check it, write the new balance" sequence would otherwise
    let two withdrawals both pass the check. In memory atomic() is a lock; against
    MongoDB it is a multi-document transaction, which also holds across separate
    server processes. Either way, a failure part-way through leaves nothing half
    applied.

    Balances change on the Account object through `_apply`, and are then handed to
    `store.save_balance`. In memory that second call does nothing, because the
    object is the stored record. In a database it is the write.
    """

    def __init__(self, store):
        self.store = store

    @property
    def audit(self) -> list[tuple]:
        """Admin actions, oldest first: (actor_user_id, action, account_id, reason).

        Kept by the store rather than on this object, so that with a database it
        survives a restart along with the balances it explains.
        """
        return self.store.audit_entries()

    # ------------------------------------------------------------------ users

    def register_user(self, name: str, email: str, role: str = "CUSTOMER",
                      password: str | None = None,
                      password_hash: str | None = None) -> User:
        """Create a user.

        `password` is the normal path: plaintext arrives, is hashed here, and then
        goes out of scope. It is never stored on the User, never logged, and never
        returned by any serializer.

        `password_hash` is the alternative for callers that already hold one. Only
        `seed.py` uses it, and only because deriving a PBKDF2 hash costs about
        0.6 seconds by design - doing that 14 times would put nine seconds on
        every server start. The seed hashes its one shared demo password once and
        hands the result to every row, which is exactly what the SQL seed script
        does with its single bcrypt hash.

        Both may be omitted, producing a user who exists but cannot log in.
        """
        if not name or not name.strip():
            raise ValueError("name is required")
        if role not in (ROLE_ADMIN, "CUSTOMER"):
            raise ValueError("role must be CUSTOMER or ADMIN")
        if password is not None and password_hash is not None:
            raise ValueError("pass password or password_hash, not both")
        if password is not None:
            password_hash = hash_password(password)
        with self.store.atomic():
            return self.store.add_user(name.strip(), email, role, password_hash)

    def search_users(self, query: str, actor: User, limit: int = 10) -> list[User]:
        """People the caller could send money to, matched on name or email.

        `actor` is taken so the caller can be left out of their own results -
        transferring to yourself is refused further down anyway, and offering it
        as a choice only invites the error.

        A word on what this exposes. It is a directory: any signed-in customer
        can type two letters and read back names and email addresses. A real
        bank does not have one, because it is a list of its customers, and you
        send money to an account number or to a payee you have already
        confirmed. It is here because a training project needs somebody to pay
        and account numbers are not memorable. If this ever stopped being a
        practice project, this method is the first thing to take out.
        """
        query = (query or "").strip()
        # Two characters minimum. One letter matches most of the roster, which
        # is not a search, it is a listing with extra steps.
        if len(query) < 2:
            return []
        # Over-fetch, because two kinds of row get dropped below and a search
        # that returned eight of ten matches would look like a broken search.
        # The client still never sees more than `limit`.
        found = self.store.search_users(query, limit * 2 + 1)
        return [u for u in found
                # An admin holds no account (see open_account), so
                # primary_account_for would refuse them. Offering one as a payee
                # is a dead end that ends in "that person has no account that
                # can receive money" after the sender has chosen them.
                if u.user_id != actor.user_id and not u.is_admin][:limit]

    def primary_account_for(self, user_id: int) -> Account:
        """The account a transfer lands in when the sender picked a person.

        The oldest active one. Which account it is matters less than it being
        the same one every time - a payee whose destination moved between two
        transfers would be a genuinely alarming thing for a bank to do.
        """
        accounts = [a for a in self.store.accounts_for_user(user_id) if a.is_active]
        if not accounts:
            raise AccountNotFound("that person has no account that can receive money")
        return min(accounts, key=lambda a: a.account_id)

    def update_profile(self, actor: User, name: str | None = None,
                       email: str | None = None) -> User:
        """Change the caller's own name or email.

        `actor` is the user from the token, and it is also the user being
        edited - there is no user_id argument, so this method cannot be pointed
        at somebody else's record no matter what the request body says. That is
        the same reasoning as `create_account` taking its owner from the cookie.

        Role is not a parameter. A profile edit that could set a role would be
        the privilege-escalation hole that registration is careful to avoid.
        """
        if name is not None and not name.strip():
            raise ValueError("name cannot be blank")
        if email is not None and not email.strip():
            raise ValueError("email cannot be blank")
        with self.store.atomic():
            return self.store.update_user(actor.user_id, name=name, email=email)

    def authenticate(self, email: str, password: str) -> User:
        """Return the user if the credentials are right, otherwise raise.

        One error message for every failure - unknown email, wrong password, user
        with no password set. A distinct "no such user" reply turns the login form
        into a tool for discovering which addresses are registered.

        When the email is unknown there is no hash to check, so this verifies
        against a throwaway one instead of returning early. Without that, an
        unknown email answers instantly while a real one takes the full PBKDF2
        time, and that difference is measurable - the timing would leak exactly
        what the shared error message was written to hide.
        """
        user = self.store.find_user_by_email(email or "")
        stored = user.password_hash if user is not None else self._decoy_hash()
        matched = verify_password(password or "", stored)
        if user is None or not matched:
            raise NotAuthorized("invalid email or password")
        return user

    _DECOY: str | None = None

    @classmethod
    def _decoy_hash(cls) -> str:
        """A real hash of a value nobody knows, used only to burn the same amount
        of time as a genuine check. Built on first use rather than at import,
        because 600,000 PBKDF2 rounds is slow enough to be felt on startup."""
        if cls._DECOY is None:
            cls._DECOY = hash_password("decoy-never-matches-anything")
        return cls._DECOY

    # --------------------------------------------------------------- accounts

    def open_account(self, owner: User, account_type: str,
                     opening_balance: int = 0) -> Account:
        """Opening balance is in cents, and is not a free gift. If it is non-zero
        it gets a ledger entry like any other credit, or reconciliation is broken
        before the account is a second old.

        AN ADMIN DOES NOT HOLD ACCOUNTS. The role exists to freeze accounts,
        correct balances and read the audit log, and every one of those powers is
        over somebody else's money. An admin who also banks here is their own
        supervisor: they could freeze their own account, adjust their own
        balance, and sign off on both in the same audit row. Refusing the account
        is cheaper than writing the rules that would have to police it.

        An admin may still open an account *for a customer* - that goes through
        the same call with the customer as `owner`, which is why the check is on
        the owner and not on the caller.
        """
        if owner.is_admin:
            raise NotAuthorized("an admin does not hold accounts")
        # parse_amount rejects zero, so an opening balance of zero skips it
        # entirely rather than being validated into a spurious error. Opening an
        # empty account is a normal thing to do; depositing nothing is not.
        opening = parse_amount(opening_balance) if opening_balance else 0
        with self.store.atomic():
            account = make_account(account_type, user_id=owner.user_id)
            self.store.add_account(account)
            if opening > 0:
                account._apply(opening)
                self.store.save_balance(account)
                self._post(account.account_id, DEPOSIT, opening, None)
            return account

    def get_account_for(self, account_id: int, actor: User) -> Account:
        """The one place ownership is checked.

        Every read and write path goes through here. The brief's design takes an
        account id and returns the account, which means that once there are user
        logins any user can read anyone's balance by changing the number.

        Raises AccountNotFound, not NotAuthorized, when the account belongs to
        somebody else. Saying "you are not allowed to see this" confirms the
        account exists, which is itself a leak.
        """
        account = self.store.get_account(account_id)
        if account.user_id != actor.user_id and not actor.is_admin:
            raise AccountNotFound(f"no account with id {account_id}")
        return account

    def get_account_to_move_money(self, account_id: int, actor: User) -> Account:
        """Fetch an account the actor may move money into or out of.

        Ownership only, and an admin is not an exception. Reading any account is
        a normal admin power; moving a customer's money through the ordinary
        customer route is not, because it leaves no record of who did it. An
        admin who has to change a balance uses adjust(), which demands a written
        reason and writes an audit row.
        """
        account = self.store.get_account(account_id)
        if account.user_id != actor.user_id:
            raise AccountNotFound(f"no account with id {account_id}")
        return account

    def my_accounts(self, actor: User) -> list[Account]:
        return self.store.accounts_for_user(actor.user_id)

    # ---------------------------------------------------------- money movement

    def deposit(self, account_id: int, amount, actor: User,
                client_txn_id: str | None = None) -> Transaction:
        # Validate before touching anything. parse_amount raises on a negative, a
        # float, three decimal places, or an amount over the per-transaction ceiling.
        amount = parse_amount(amount)
        with self.store.atomic():
            # Ownership first: a caller who may not see this account must not be
            # able to learn from the error whether it is frozen or does not exist.
            account = self.get_account_to_move_money(account_id, actor)
            self._guard_idempotency(client_txn_id)
            if not account.is_active:
                raise AccountNotActive(f"account {account_id} is {account.status.lower()}")

            # The balance change and its ledger entry commit together or not at all.
            account._apply(amount)
            self.store.save_balance(account)
            return self._post(account_id, DEPOSIT, amount, client_txn_id)

    def withdraw(self, account_id: int, amount, actor: User,
                 client_txn_id: str | None = None) -> Transaction:
        amount = parse_amount(amount)
        with self.store.atomic():
            account = self.get_account_to_move_money(account_id, actor)
            self._guard_idempotency(client_txn_id)
            if not account.is_active:
                raise AccountNotActive(f"account {account_id} is {account.status.lower()}")

            # Note this asks the account, rather than comparing to account.balance.
            # A savings account holds a minimum, so "the balance" and "what may leave"
            # are different numbers. Asking the object keeps that difference in one
            # place instead of spreading isinstance checks through this method.
            if not account.can_withdraw(amount):
                available = account.available_for_withdrawal()
                raise InsufficientFunds(
                    f"insufficient funds: requested {amount}, available {available}"
                )

            # Check and write sit inside one atomic block, so no second request can
            # slip between them and spend the same money twice.
            account._apply(-amount)
            self.store.save_balance(account)
            return self._post(account_id, WITHDRAWAL, amount, client_txn_id)

    def transfer(self, from_id: int, to_id: int, amount, actor: User,
                 client_txn_id: str | None = None) -> tuple[Transaction, Transaction]:
        """Both legs happen or neither does.

        store.atomic() is what makes that true: a lock in memory, and in MongoDB a
        multi-document transaction, where both balance updates and both ledger
        entries commit together or roll back together.
        """
        amount = parse_amount(amount)
        if from_id == to_id:
            raise ValueError("cannot transfer to the same account")
        with self.store.atomic():
            source = self.get_account_to_move_money(from_id, actor)  # owner only
            target = self.store.get_account(to_id)          # recipient need not be yours
            self._guard_idempotency(client_txn_id)
            if not source.is_active or not target.is_active:
                raise AccountNotActive("both accounts must be active")
            if not source.can_withdraw(amount):
                raise InsufficientFunds(
                    f"insufficient funds: requested {amount}, "
                    f"available {source.available_for_withdrawal()}"
                )

            # Four writes, all or nothing. Every check that could fail has already
            # run, so nothing below raises and leaves one leg applied.
            source._apply(-amount)
            target._apply(amount)
            self.store.save_balance(source)
            self.store.save_balance(target)
            out = self._post(from_id, TRANSFER_OUT, amount, client_txn_id)
            inn = self._post(to_id, TRANSFER_IN, amount, None)
            return out, inn

    def history(self, account_id: int, actor: User, page: int = 1,
                page_size: int = 20, txn_type: str | None = None):
        """Returns (rows, total). Paginated from the start so the UI never has to
        change shape later."""
        self.get_account_for(account_id, actor)
        rows = self.store.transactions_for_account(account_id, txn_type)
        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        start = (page - 1) * page_size
        return rows[start:start + page_size], len(rows)

    # ------------------------------------------------------------------ admin

    def set_frozen(self, account_id: int, frozen: bool, reason: str, actor: User) -> Account:
        self._require_admin(actor)
        self._require_reason(reason)
        with self.store.atomic():
            account = self.store.get_account(account_id)
            account.status = FROZEN if frozen else ACTIVE
            self.store.save_status(account)
            self._log(actor, "FREEZE" if frozen else "UNFREEZE", account_id, reason)
            return account

    def adjust(self, account_id: int, amount, direction: str,
               reason: str, actor: User) -> Transaction:
        """Admin correction.

        There is deliberately no `set_balance`. It is the easiest admin feature to
        write and the wrong one: a balance that moves without a matching ledger
        entry breaks `balance == sum(ledger)` permanently, and afterwards there is
        no way to tell which of the two is right.

        Adjustments may touch a frozen account, since correcting one is a normal
        reason to have frozen it. They never skip the ledger or the audit log.
        """
        self._require_admin(actor)
        self._require_reason(reason)
        amount = parse_amount(amount)
        if direction not in ("CREDIT", "DEBIT"):
            raise ValueError("direction must be CREDIT or DEBIT")
        with self.store.atomic():
            account = self.store.get_account(account_id)

            delta = amount if direction == "CREDIT" else -amount
            account._apply(delta)  # raises InsufficientFunds if it would go negative
            self.store.save_balance(account)
            txn = self._post(account_id, DEPOSIT if direction == "CREDIT" else WITHDRAWAL,
                             amount, None, adjusted_by=actor.user_id,
                             reason=reason.strip())
            self._log(actor, f"ADJUST_{direction}", account_id, reason)
            return txn

    def all_accounts(self, actor: User) -> list[Account]:
        self._require_admin(actor)
        return self.store.all_accounts()

    def all_users(self, actor: User) -> list[User]:
        self._require_admin(actor)
        return self.store.all_users()

    def audit_log(self, actor: User) -> list[tuple]:
        """The admin audit trail. Read-only, and a copy, so a caller cannot append
        to it by holding the list."""
        self._require_admin(actor)
        return self.store.audit_entries()

    def reconciliation_report(self, actor: User) -> list[tuple[int, int, int]]:
        """`reconcile_all()` with the role check attached.

        Exists so the controller has a public method to call. `reconcile_all()`
        itself takes no actor, because the tests and the demo run it without one;
        this is the door for anything that arrives over HTTP.
        """
        self._require_admin(actor)
        return self.reconcile_all()

    # ------------------------------------------------------------ invariants

    def reconcile(self, account_id: int) -> tuple[int, int]:
        """Returns (stored_balance, ledger_sum) in cents. These must always be
        equal, and on integers that equality is exact.

        Run this after every test and in the demo. If it ever disagrees, a balance
        was changed somewhere without a matching ledger entry.
        """
        account = self.store.get_account(account_id)
        return account.balance, self.store.ledger_sum(account_id)

    def reconcile_all(self) -> list[tuple[int, int, int]]:
        """Every account that fails reconciliation. Should always be empty."""
        # One call for every total, not one per account. `reconcile()` is still
        # the right thing for a single account; doing it in a loop meant a round
        # trip each, which is what made this the slowest endpoint in the app.
        sums = self.store.ledger_sums()
        broken = []
        for account in self.store.all_accounts():
            ledger = sums.get(account.account_id, 0)
            if account.balance != ledger:
                broken.append((account.account_id, account.balance, ledger))
        return broken

    # -------------------------------------------------------------- internals

    def _post(self, account_id: int, txn_type: str, amount: int,
              client_txn_id: str | None, adjusted_by: int | None = None,
              reason: str | None = None) -> Transaction:
        """Write the ledger entry. Called immediately after every balance change,
        with no branch in between that could skip it.

        adjusted_by and reason are set only by adjust(), which is what makes an
        admin correction distinguishable from a customer's own deposit.
        """
        return self.store.add_transaction(
            Transaction(
                txn_id=self.store.next_txn_id(),
                account_id=account_id,
                txn_type=txn_type,
                amount=amount,
                client_txn_id=client_txn_id,
                adjusted_by=adjusted_by,
                reason=reason,
            )
        )

    def _guard_idempotency(self, client_txn_id: str | None) -> None:
        """A double-clicked submit button sends the same id twice.

        In memory this is a set lookup. With a database it becomes a UNIQUE index,
        which is the version that actually holds under concurrency.
        """
        if self.store.client_txn_id_seen(client_txn_id):
            raise DuplicateTransaction(
                f"transaction {client_txn_id} has already been submitted"
            )

    @staticmethod
    def _require_admin(actor: User) -> None:
        if not actor.is_admin:
            raise NotAuthorized("admin role required")

    @staticmethod
    def _require_reason(reason: str) -> None:
        if not reason or len(reason.strip()) < 10:
            raise ValueError("a written reason of at least 10 characters is required")

    def _log(self, actor: User, action: str, account_id: int | None, reason: str) -> None:
        self.store.add_audit_entry(actor.user_id, action, account_id, reason.strip())
