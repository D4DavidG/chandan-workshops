"""Simple Bank Application: backend.

Standard library only, except mongo_store.py, which needs pymongo
(pip install -r requirements.txt). Nothing imports it unless the server is
configured to use MongoDB, so the tests and the demo still install nothing.

Layers, outermost first. Each one depends only on the layer below it, which is
what makes the arrow in the brief's architecture diagram true rather than
aspirational:

    api.py          Controller. HTTP in, JSON out. No business rules.
    serializers.py  Domain objects -> JSON dicts. Money goes out as integer cents.
    services.py     Every business rule. No HTTP, no SQL, no framework.
    models.py       User, Account, Transaction as plain classes.
    store.py        In-memory repository. Used by the tests and the demo.
    mongo_store.py  MongoDB repository, same method names. Used by the server.
    config.py       Reads .env into the environment.
    money.py        Cents as ints, and amount validation. Read this first.
    security.py     Password hashing and signed JSON Web Tokens.
    errors.py       Domain exceptions. Not HTTP status codes.
    seed.py         The demo roster, replayed through the real service methods.

Used as a library:

    from bank import BankStore, BankService

    store = BankStore()
    svc = BankService(store)
    alice = svc.register_user("Alice", "alice@example.com", password="hunter2!!")
    acct = svc.open_account(alice, "CHECKING", 10000)   # amounts are cents:
    svc.deposit(acct.account_id, 2550, alice)           # 100.00, then 25.50

Used as an API:

    python server.py            # then see README.md for the endpoint table
"""
from .api import BankAPI, serve
from .errors import (
    AccountNotActive, AccountNotFound, BankError, ConcurrentUpdate, DuplicateTransaction,
    EmailAlreadyUsed, InsufficientFunds, InvalidAmount, NotAuthorized,
    StaleIdCounter, StorageUnavailable, UserNotFound,
)
from .models import (
    ACTIVE, DEPOSIT, FROZEN, ROLE_ADMIN, ROLE_CUSTOMER, TRANSFER_IN,
    TRANSFER_OUT, WITHDRAWAL, Account, CheckingAccount, CreditAccount,
    SavingsAccount, Transaction, User, make_account,
)
from .money import format_money, parse_amount, to_cents
from .security import hash_password, issue_token, read_token, verify_password
from .serializers import account_json, transaction_json, user_json
from .services import BankService
from .store import BankStore

__all__ = [
    # service and storage
    "BankService", "BankStore",
    # api
    "BankAPI", "serve",
    # domain types
    "User", "Account", "CheckingAccount", "CreditAccount", "SavingsAccount",
    "Transaction", "make_account",
    # money
    "to_cents", "parse_amount", "format_money",
    # security
    "hash_password", "verify_password", "issue_token", "read_token",
    # serialization
    "user_json", "account_json", "transaction_json",
    # errors
    "BankError", "InsufficientFunds", "AccountNotActive", "AccountNotFound",
    "UserNotFound", "EmailAlreadyUsed", "NotAuthorized", "InvalidAmount",
    "DuplicateTransaction", "ConcurrentUpdate", "StaleIdCounter", "StorageUnavailable",
    # constants
    "DEPOSIT", "WITHDRAWAL", "TRANSFER_IN", "TRANSFER_OUT", "ACTIVE", "FROZEN",
    "ROLE_ADMIN", "ROLE_CUSTOMER",
]
