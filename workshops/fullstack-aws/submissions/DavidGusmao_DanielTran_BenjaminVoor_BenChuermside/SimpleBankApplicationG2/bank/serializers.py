"""Turning domain objects into the dictionaries that become JSON.

This is a thin layer with one strong opinion, and the opinion is the reason the
layer exists at all rather than the controller calling `dataclasses.asdict`.

MONEY IS SERIALIZED AS AN INTEGER NUMBER OF CENTS
-------------------------------------------------
The brief's sample response is:

    {"accountId": 1, "userName": "John Doe", "balance": 1000.00}

`1000.00` there is a fractional JSON number, and that is where the precision this
codebase is careful about everywhere else would get thrown away. JSON has one
numeric type, and every JavaScript client turns a fractional literal into an IEEE
754 double the instant `JSON.parse` runs.

An *integer* does not have that problem. JSON integers are exact up to 2^53,
which is roughly ninety trillion dollars expressed in cents, so the number the
server holds is precisely the number the browser receives:

    {"accountId": 1, "userName": "Aaron Forrester", "balance": 123456}

That is 1,234.56. The frontend divides by 100 for display and never for
arithmetic - it renders the balance the server returned rather than computing
one - and sends amounts back the same way, as whole cents.

This replaces an earlier design that sent `"1234.56"` as a quoted string. The
string was there to stop `Decimal` precision being lost to a float on the way
out; with cents as integers there is nothing to lose, and a client that used to
parse a string now reads a number directly.

TWO THINGS ARE NEVER IN A RESPONSE
----------------------------------
`password_hash`, and any field the caller is not entitled to. Serializing by
naming each field explicitly - rather than dumping an object's `__dict__` - is
what makes that guarantee hold when someone adds a column later: a new field is
invisible to the API until somebody deliberately adds it here.

NAMING
------
Snake_case inside Python, camelCase on the wire, matching the brief's samples and
the convention a React client expects. The translation happens here and only here.
"""
from .models import Account, Transaction, User


def money(cents: int) -> int:
    """The rule from the module docstring, in one place.

    It is an identity function today, and it stays because it is the one seam
    where the wire representation of money is decided. When this returned a
    formatted string it was the only edit needed to change that format; keeping
    it means the next such change is still one function rather than nine call
    sites, and `grep money(` still lists every monetary field in the API.

    Deliberately not `format_money`: no thousands separators and no currency
    symbol. Grouping and symbols are presentation, they vary by locale, and they
    have no business in an interchange format.
    """
    return cents


def user_json(user: User) -> dict:
    """Public view of a user. Note which field is absent."""
    return {
        "userId": user.user_id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "createdAt": user.created_at.isoformat(),
        # password_hash is deliberately not here, and never will be.
    }


def account_json(account: Account, owner: User | None = None) -> dict:
    """Public view of an account.

    `availableForWithdrawal` is included alongside `balance` because for a savings
    account they differ, and a client that computes "available" for itself would
    have to duplicate the minimum-balance rule. Sending both means the rule stays
    in one place - the `Account` subclass - and the UI can grey out the submit
    button without knowing why.

    Every monetary field here is cents: `"balance": 123456` is 1,234.56.
    """
    payload = {
        "accountId": account.account_id,
        "userId": account.user_id,
        "accountType": account.account_type,
        "status": account.status,
        "balance": money(account.balance),
        "availableForWithdrawal": money(account.available_for_withdrawal()),
        "minimumBalance": money(account.minimum_balance),
        "createdAt": account.created_at.isoformat(),
    }
    if owner is not None:
        # The brief's Account Response carries "userName", so it is here when the
        # caller has the owner to hand. Optional, because the common list endpoint
        # already knows every account belongs to the caller.
        payload["userName"] = owner.name
    return payload


def transaction_json(txn: Transaction) -> dict:
    """Public view of one ledger entry.

    `amount` is always positive and `direction` carries the sign, matching how the
    row is stored. `signedAmount` is supplied as well so a client can sum a page
    without re-deriving which types are credits - that mapping lives in
    `models.CREDIT_TYPES` and should not be copied into a frontend.

    `amount` and `signedAmount` are cents: `"amount": 2500` is 25.00.
    """
    payload = {
        "txnId": txn.txn_id,
        "accountId": txn.account_id,
        "type": txn.txn_type,
        "amount": money(txn.amount),
        "signedAmount": money(txn.signed_amount),
        "direction": "CREDIT" if txn.signed_amount > 0 else "DEBIT",
        "clientTxnId": txn.client_txn_id,
        "createdAt": txn.created_at.isoformat(),
    }
    if txn.adjusted_by is not None:
        # Only an admin adjustment carries these, so an ordinary deposit keeps
        # exactly the shape it had before.
        payload["adjustedBy"] = txn.adjusted_by
        payload["reason"] = txn.reason
    return payload


def page_json(rows: list, total: int, page: int, page_size: int) -> dict:
    """Envelope for a paginated list.

    Paginated from the first day even though the seed data fits on one screen.
    Adding pagination later changes the response shape, which breaks every client
    that consumed the bare array, so the array is inside an envelope from the
    start and the cost of that decision is one word of nesting.
    """
    return {
        "items": rows,
        "page": page,
        "pageSize": page_size,
        "total": total,
        # Ceiling division without importing math: how many pages the client can ask for.
        "totalPages": (total + page_size - 1) // page_size if page_size else 0,
    }
