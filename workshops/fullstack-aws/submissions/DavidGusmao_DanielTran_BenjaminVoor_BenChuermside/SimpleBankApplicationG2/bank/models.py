"""Domain classes. Plain Python objects, no framework, no database.

This is the Day 1 Module 2 material (methods, parameters, scope, overloading)
applied to the bank domain rather than to exercises.

Three object-oriented decisions worth defending in review:

1. **Encapsulation of `balance`.** `Account.balance` is a read-only property backed
   by `_balance`. There is no setter. The only way to change a balance is `_apply`,
   which is called by the service layer alongside a ledger entry. If `balance` were
   a public attribute, any line of code anywhere could set it and the invariant
   `balance == sum(ledger)` would be unenforceable.

2. **Inheritance with a real difference.** `CheckingAccount` and `SavingsAccount`
   differ in one rule: how much of the balance may actually leave. That difference
   lives in an overridden `minimum_balance`, read by `available_for_withdrawal()`,
   so the withdraw logic in the service layer does not branch on account type.
   Adding a third account type later means adding a class, not editing an `if`.

   `SavingsAccount.MINIMUM` is 0.00 at the moment, which makes the two types
   behave identically today. That is a policy setting, not a change of shape: the
   polymorphic path is what the service layer calls either way, so a floor can
   come back by editing one constant rather than by threading a new rule through
   `withdraw`, `transfer` and the serializers.

3. **Python has no method overloading.** That was question 2 of Module 2. Java
   picks between same-named methods by parameter list at compile time; Python
   binds one name to one function, so a second `def` of the same name simply
   replaces the first. The Python equivalents are default arguments and
   `functools.singledispatch`. `Transaction.create()` below uses a classmethod as
   a named alternative constructor, which is the idiomatic answer to what
   overloaded constructors are for.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .errors import InsufficientFunds
from .money import format_money, to_cents

# Ledger entry types. A transaction stores a positive amount and takes its
# direction from the type, so this pair is the single source of truth for sign.
DEPOSIT = "DEPOSIT"
WITHDRAWAL = "WITHDRAWAL"
TRANSFER_IN = "TRANSFER_IN"
TRANSFER_OUT = "TRANSFER_OUT"

CREDIT_TYPES = frozenset({DEPOSIT, TRANSFER_IN})
DEBIT_TYPES = frozenset({WITHDRAWAL, TRANSFER_OUT})

ROLE_CUSTOMER = "CUSTOMER"
ROLE_ADMIN = "ADMIN"

ACTIVE = "ACTIVE"
FROZEN = "FROZEN"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class User:
    """A person. Carries the two columns the brief's `users` table does not have.

    `password_hash` is the opaque string produced by `security.hash_password`, and
    it is the only representation of a password that ever exists in this program:
    the plaintext is read from the request, passed straight to the hasher, and
    never stored on any object. It is nullable because a user may be created
    without one (the seed roster does this), in which case that user cannot log in.

    `role` is a constrained string rather than a separate roles table. At two roles
    a join table is the more correct model and the wrong amount of machinery.
    """

    user_id: int
    name: str
    email: str
    role: str = ROLE_CUSTOMER
    password_hash: str | None = None
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self):
        # Normalise once, here, rather than at every call site. Email is the login
        # identifier, so "Aaron@Example.com" and "aaron@example.com" must not be
        # able to become two different accounts.
        self.email = self.email.strip().lower()

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"


@dataclass(frozen=True)
class Transaction:
    """One immutable ledger entry.

    Entries are never modified and never removed. A correction is a new entry of
    the opposite direction. `frozen=True` on the dataclass makes that a property
    of the type rather than a convention people have to remember.
    """

    txn_id: int
    account_id: int
    txn_type: str
    amount: int          # cents, always positive; the sign lives in txn_type
    client_txn_id: str | None = None
    created_at: datetime = field(default_factory=_now)
    # Set only by an admin adjustment, so a correction is never mistaken for a
    # customer's own deposit. The audit log records the same facts, but somebody
    # reading one account's history should not have to cross-reference it.
    adjusted_by: int | None = None
    reason: str | None = None

    @property
    def signed_amount(self) -> int:
        """What this entry contributes to the balance, in cents."""
        return self.amount if self.txn_type in CREDIT_TYPES else -self.amount

    def __str__(self) -> str:
        sign = "+" if self.txn_type in CREDIT_TYPES else "-"
        # Sign as well as colour. Never signal credit or debit by colour alone;
        # red/green is the most common colour-vision deficiency axis.
        return f"#{self.txn_id:<4} {self.created_at:%Y-%m-%d}  {self.txn_type:<13} {sign}{format_money(self.amount):>12}"


class Account:
    """Base account. Do not instantiate directly; use a subclass.

    `account_id` starts as None and is assigned by `BankStore.add_account`.
    Allocating identity is the storage layer's job - it is what a database does
    with AUTO_INCREMENT - and an object that numbers itself cannot be handed to a
    different store without the numbers colliding. An earlier version of this
    class held a class-level `itertools.count`, which meant every account ever
    created in the process shared one sequence, so ids depended on how many other
    tests had run first.
    """

    def __init__(self, user_id: int, account_id: int | None = None,
                 opening_balance: int = 0, status: str = ACTIVE):
        self.account_id = account_id
        self.user_id = user_id
        self._balance = to_cents(opening_balance)
        self.status = status
        self.created_at = _now()

    # ---- encapsulation ----

    @property
    def balance(self) -> int:
        """Cents. Read-only on purpose - see the module docstring."""
        return self._balance

    def _apply(self, delta: int) -> None:
        """Internal. Only the service layer calls this, and only with a matching
        ledger entry. The leading underscore is the signal that reaching for this
        from ordinary code means something has gone wrong."""
        new_balance = self._balance + to_cents(delta)
        if new_balance < 0:
            raise InsufficientFunds("operation would take the balance below zero")
        self._balance = new_balance

    # ---- polymorphic rule ----

    @property
    def account_type(self) -> str:
        raise NotImplementedError

    @property
    def minimum_balance(self) -> int:
        return 0

    def available_for_withdrawal(self) -> int:
        """How much may actually leave, in cents. Subclasses change this, not the
        caller."""
        return self._balance - self.minimum_balance

    def can_withdraw(self, amount: int) -> bool:
        return self.is_active and to_cents(amount) <= self.available_for_withdrawal()

    @property
    def is_active(self) -> bool:
        return self.status == ACTIVE

    def __str__(self) -> str:
        return (f"[{self.account_id:>3}] {self.account_type:<9} "
                f"{format_money(self._balance):>13}  {self.status}")

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(account_id={self.account_id}, "
                f"user_id={self.user_id}, balance={self._balance})")


class CheckingAccount(Account):
    @property
    def account_type(self) -> str:
        return "CHECKING"


class SavingsAccount(Account):
    """Holds a minimum balance. This is the only behavioural difference, and it
    is expressed by overriding `minimum_balance` rather than by the service layer
    checking `isinstance`.

    The minimum is currently 0.00, so in practice a savings account behaves like
    a checking account today. The override is still the seam: raising this one
    constant is the entire change needed to reintroduce a floor, and no service,
    route or test has to learn about it.
    """

    MINIMUM = 0  # cents

    @property
    def account_type(self) -> str:
        return "SAVINGS"

    @property
    def minimum_balance(self) -> int:
        return self.MINIMUM


class CreditAccount(Account):
    """The credit card product.

    WHAT THIS IS NOT, AND IT MATTERS
    --------------------------------
    A real credit account is the mirror image of the other two: you spend money
    you do not have, the balance goes negative, and a credit *limit* says how
    far. This one cannot do that. `Account._apply` refuses to take a balance
    below zero and `can_withdraw` measures against what is actually in there, so
    this behaves exactly like a checking account that happens to be a different
    colour on screen.

    That is a deliberate stopping point, not an oversight. Letting a balance go
    negative touches the overdraft rule, the reconciliation report and every
    `available_for_withdrawal` caller at once, and none of that is in the brief.
    Doing it properly means giving Account a `credit_limit`, letting
    `minimum_balance` return a negative number, and revisiting the reconciliation
    query - at which point the seam below is where it starts.
    """

    @property
    def account_type(self) -> str:
        return "CREDIT"


ACCOUNT_TYPES = {
    "CHECKING": CheckingAccount,
    "SAVINGS": SavingsAccount,
    "CREDIT": CreditAccount,
}


def make_account(account_type: str, user_id: int, **kwargs) -> Account:
    """Factory. Keeps `ACCOUNT_TYPES` the one place that knows the mapping."""
    try:
        cls = ACCOUNT_TYPES[account_type.upper()]
    except KeyError:
        raise ValueError(f"unknown account type: {account_type!r}") from None
    return cls(user_id=user_id, **kwargs)
