"""Domain errors.

These are business concepts, not HTTP status codes and not database errors. That
is deliberate: the service layer raises `InsufficientFunds`, not "409", which is
what lets the same rules serve an HTTP API, a console demo, and a test suite
without any of them knowing about the others.

The translation to HTTP happens in exactly one place - the `ERROR_STATUS` table
at the top of `api.py`. If a new error class is added here, add a row there too,
or it falls through to a 500.

Every class is empty. That is the point: the class itself is the information. A
caller distinguishes "not enough money" from "account is frozen" by catching a
different type, not by reading a message string, and a message is free to be
reworded without breaking anything.
"""


class BankError(Exception):
    """Base for everything this package raises.

    `except BankError` catches every expected domain failure and nothing else, so
    a genuine bug - a TypeError, a KeyError - still escapes and gets noticed
    instead of being swallowed as "some banking problem".
    """


class InsufficientFunds(BankError):
    """The withdrawal or transfer exceeds what may leave the account.

    Note "what may leave", not "the balance": a savings account holds a minimum,
    so the two differ. See `Account.available_for_withdrawal`.
    """


class AccountNotActive(BankError):
    """The account is frozen. Customer-initiated movement is refused; an admin
    adjustment is still allowed, because correcting an account is a normal reason
    to have frozen it."""


class AccountNotFound(BankError):
    """No such account - OR the account exists and belongs to somebody else.

    Those two cases raise the same exception with the same message on purpose. A
    distinct "you are not allowed to see this" confirms the account is real,
    which is the fact the error is withholding. See `get_account_for`.
    """


class UserNotFound(BankError):
    pass


class EmailAlreadyUsed(BankError):
    """The `UNIQUE` constraint on `users.email`, as a domain concept."""


class NotAuthorized(BankError):
    """The caller lacks the role for this action, or their credentials are wrong.

    Maps to 403. The one exception is a failed login, which `api.login` converts
    to 401: 401 means "authenticate", 403 means "authenticating again will not
    help".
    """


class InvalidAmount(BankError, ValueError):
    """Subclasses ValueError too, so `except ValueError` still catches it.

    Inheriting from both means callers that reasonably treat a bad amount as an
    ordinary value error keep working, without losing the ability to catch it
    specifically as a banking concern.
    """


class DuplicateTransaction(BankError):
    """This `client_txn_id` has already been applied - the double-clicked submit
    button. Refusing is what stops the second click depositing again."""


class StaleIdCounter(BankError):
    """The stored id counter is behind the records it numbers.

    Raised when the counter hands out an id that already exists, which happens
    when rows arrive without their counter: an import, a restore, or a seeder
    that numbered them some other way. It is a setup problem, not a request
    problem - retrying will fail identically - so it maps to 500 rather than 409,
    and the message says how to repair it.
    """


class StorageUnavailable(BankError):
    """The database could not be reached.

    Maps to 503. The request itself was fine and nothing was changed, so the
    caller can simply try again. Only a database-backed store raises it.
    """


class ConcurrentUpdate(BankError):
    """Another request changed the same data first, so this one was rolled back.

    Maps to 409. It is the database's write-conflict protection doing its job:
    two simultaneous withdrawals cannot both spend the same money, so one is
    refused whole rather than half applied. Retrying is safe.
    """
