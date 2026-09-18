"""MongoDB repository, with the same method names as the in-memory BankStore.

The service layer calls add_account, get_account, add_transaction and the rest
without knowing which store it was given. This class answers them from MongoDB,
so data survives a restart and every server pointed at the same database sees the
same records. Atlas setup is in the README.

What the in-memory store does in Python, this one hands to the database:

    in memory                     here
    ----------------------------  ------------------------------------------------
    itertools.count() ids         a counters collection, incremented atomically
    the email dict                a unique index on users.email
    the set of client txn ids     a unique index on transactions.client_txn_id
    a lock around each change     a multi-document transaction, from atomic()

Sessions are not here. A JWT is signed rather than stored, so there is no
sessions or tokens collection to keep - see bank/security.py.

Money is a plain integer number of cents. BSON has a 64-bit integer type and a
Python int maps onto it exactly, so no amount is ever stored as a Double.

Driver errors do not leave this file. A lost connection becomes
StorageUnavailable and a write conflict becomes ConcurrentUpdate, so the
controller can answer 503 and 409 without importing pymongo.
"""
import functools
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import re

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import (
    ConnectionFailure, DuplicateKeyError, OperationFailure, PyMongoError,
)

from .errors import (
    AccountNotFound, ConcurrentUpdate, DuplicateTransaction, EmailAlreadyUsed,
    StaleIdCounter, StorageUnavailable, UserNotFound,
)
from .models import CREDIT_TYPES, Account, Transaction, User, make_account

COLLECTIONS = ("users", "accounts", "transactions", "counters", "audit_log")

# MongoDB's error code for two transactions trying to change one document.
WRITE_CONFLICT = 112


def _collided_on(exc: DuplicateKeyError, field: str) -> bool:
    """Whether a duplicate-key error came from an index on `field`.

    pymongo reports the offending index in `keyPattern`, so a collision on
    `email` and a collision on `_id` are distinguishable - and they mean
    completely different things. Falls back to the message text, which is all
    older servers supply.
    """
    pattern = (exc.details or {}).get("keyPattern")
    if isinstance(pattern, dict):
        return field in pattern
    return field in str(exc)


def _translate(exc: PyMongoError) -> Exception:
    """The domain error for a driver error, or the driver error itself if none fits."""
    if isinstance(exc, ConnectionFailure):
        return StorageUnavailable(
            "the database is unavailable right now; nothing was changed, "
            "please try again shortly")
    if exc.has_error_label("TransientTransactionError") or (
            isinstance(exc, OperationFailure) and exc.code == WRITE_CONFLICT):
        return ConcurrentUpdate(
            "the account was changed by another request at the same moment; "
            "nothing was applied, please try again")
    return exc


def _guarded(method):
    """Translate driver errors raised by a store method into domain errors."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except PyMongoError as exc:
            translated = _translate(exc)
            if translated is exc:
                raise
            raise translated from exc
    return wrapper


# ------------------------------------------------------------------ documents

def _user_from(doc: dict) -> User:
    return User(user_id=doc["_id"], name=doc["name"], email=doc["email"],
                role=doc["role"], password_hash=doc.get("password_hash"),
                created_at=doc["created_at"])


def _account_from(doc: dict) -> Account:
    account = make_account(doc["account_type"], user_id=doc["user_id"],
                           account_id=doc["_id"], opening_balance=doc["balance"],
                           status=doc["status"])
    account.created_at = doc["created_at"]
    return account


def _transaction_from(doc: dict) -> Transaction:
    return Transaction(txn_id=doc["_id"], account_id=doc["account_id"],
                       txn_type=doc["txn_type"], amount=doc["amount"],
                       client_txn_id=doc.get("client_txn_id"),
                       created_at=doc["created_at"],
                       adjusted_by=doc.get("adjusted_by"), reason=doc.get("reason"))


class MongoStore:
    """A repository backed by one database inside a MongoDB cluster."""

    def __init__(self, uri: str, db_name: str, *, timeout_ms: int = 10_000):
        if not db_name:
            raise ValueError("a database name is required")
        self.db_name = db_name
        # tz_aware so dates come back in UTC, matching the ones models.py creates.
        self._client = MongoClient(uri, tz_aware=True,
                                   serverSelectionTimeoutMS=timeout_ms)
        self._db = self._client[db_name]
        self._users = self._db["users"]
        self._accounts = self._db["accounts"]
        self._transactions = self._db["transactions"]
        self._counters = self._db["counters"]
        self._audit = self._db["audit_log"]
        # The session of the transaction running on this thread, if there is one.
        # Every read and write inside atomic() must go through it, or it would
        # happen outside the transaction and could not be rolled back.
        self._local = threading.local()
        # One transaction at a time per server process. Without this, two requests
        # handled by the same server could collide in the database and one would
        # be refused with ConcurrentUpdate; with it, they queue instead. The
        # transaction is still what protects against other server processes,
        # which this lock cannot see.
        self._lock = threading.RLock()
        self.ensure_indexes()

    # ---- setup and housekeeping ----

    @_guarded
    def ensure_indexes(self) -> None:
        """Create the collections and indexes if they do not exist. Safe to repeat."""
        existing = set(self._db.list_collection_names())
        for name in COLLECTIONS:
            if name not in existing:
                self._db.create_collection(name)
        # The UNIQUE constraint on users.email, enforced by the database.
        self._index(self._users, [("email", ASCENDING)], unique=True,
                    name="email_unique")
        self._index(self._accounts, [("user_id", ASCENDING)], name="by_owner")
        # The idempotency guarantee. Partial, so the many transactions without a
        # client id do not all collide on a shared null.
        self._index(
            self._transactions,
            [("client_txn_id", ASCENDING)], unique=True, name="client_txn_id_unique",
            partialFilterExpression={"client_txn_id": {"$type": "string"}})
        self._index(self._transactions,
                    [("account_id", ASCENDING), ("_id", DESCENDING)], name="history")

    @staticmethod
    def _index(collection, keys, **options) -> None:
        """create_index, tolerating an equivalent index under a different name.

        create_index is idempotent only for an exact match. If the same keys
        already exist under another name, MongoDB raises IndexOptionsConflict
        (85) and, without this, every MongoStore() against that database would
        fail in the constructor - so one stale index makes the whole application
        unusable rather than just untidy.

        That is not hypothetical. An earlier version of this file named these
        indexes uq_user_email and uq_client_txn, and any database it touched
        still carries them. The index does the same job whatever it is called,
        so the right answer is to accept the one already there.
        """
        from pymongo.errors import OperationFailure

        try:
            collection.create_index(keys, **options)
        except OperationFailure as exc:
            if exc.code != 85:          # IndexOptionsConflict
                raise

    @_guarded
    def ping(self) -> None:
        self._client.admin.command("ping")

    @_guarded
    def is_empty(self) -> bool:
        return self._users.count_documents({}, limit=1) == 0

    @_guarded
    def reset(self) -> None:
        """Delete every collection this store owns, then rebuild the indexes.

        This destroys all data in the database. It exists for server.py --reset
        and for the integration tests, which only ever use simple_bank_test.
        """
        for name in COLLECTIONS:
            self._db.drop_collection(name)
        self.ensure_indexes()

    def close(self) -> None:
        self._client.close()

    # ---- units of work ----

    @property
    def _session(self):
        return getattr(self._local, "session", None)

    @contextmanager
    def atomic(self):
        """Run a group of reads and writes as one multi-document transaction.

        Everything inside commits together or rolls back together, and MongoDB
        refuses a transaction that would overwrite a change another one made
        after it started. That second property is what stops two withdrawals on
        different servers from spending the same money.

        Nested calls join the transaction already open on this thread.
        """
        if self._session is not None:
            yield
            return
        with self._lock:
            try:
                with self._client.start_session() as session:
                    with session.start_transaction():
                        self._local.session = session
                        try:
                            yield
                        finally:
                            self._local.session = None
            except PyMongoError as exc:
                translated = _translate(exc)
                if translated is exc:
                    raise
                raise translated from exc

    def _next_id(self, name: str) -> int:
        """The next integer id for a collection, like AUTO_INCREMENT.

        Deliberately outside any transaction. Otherwise every request that creates
        a record would queue behind every other one on this single counter
        document, including requests for unrelated accounts. The cost is the same
        as in SQL: a request that rolls back leaves a gap in the numbering, which
        is harmless, where reusing a number would not be.
        """
        doc = self._counters.find_one_and_update(
            {"_id": name}, {"$inc": {"seq": 1}}, upsert=True,
            return_document=ReturnDocument.AFTER)
        return doc["seq"]

    # ---- users ----

    @_guarded
    def add_user(self, name: str, email: str, role: str = "CUSTOMER",
                 password_hash: str | None = None) -> User:
        key = email.strip().lower()
        if self._users.find_one({"email": key}, {"_id": 1}, session=self._session):
            raise EmailAlreadyUsed(f"email already registered: {key}")
        user = User(user_id=self._next_id("users"), name=name, email=key, role=role,
                    password_hash=password_hash)
        try:
            self._users.insert_one({
                "_id": user.user_id, "name": user.name, "email": user.email,
                "role": user.role, "password_hash": user.password_hash,
                "created_at": user.created_at,
            }, session=self._session)
        except DuplicateKeyError as exc:
            # Which index rejected it decides what actually went wrong, and the
            # two causes have nothing to do with each other.
            if _collided_on(exc, "email"):
                # Two registrations raced past the check above. The index settles it.
                raise EmailAlreadyUsed(f"email already registered: {key}") from None
            # The collision was on _id, so the counter is behind the data: it
            # handed out a number some record already has. Reporting that as a
            # duplicate email sends you looking through the users collection for
            # an address that is not there.
            raise StaleIdCounter(
                f"the id counter for 'users' is behind the data: it produced "
                f"{user.user_id}, which already exists. This happens when records "
                f"were loaded without their counter - an import, a restore, or a "
                f"seeder that numbered them differently. Reload the database with "
                f"`python server.py --reset`, or set counters/_id='users' above "
                f"the highest existing _id."
            ) from None
        return user

    @_guarded
    def get_user(self, user_id: int) -> User:
        doc = self._users.find_one({"_id": user_id}, session=self._session)
        if doc is None:
            raise UserNotFound(f"no user with id {user_id}")
        return _user_from(doc)

    @_guarded
    def find_user_by_email(self, email: str) -> User | None:
        doc = self._users.find_one({"email": email.strip().lower()},
                                   session=self._session)
        return _user_from(doc) if doc is not None else None

    @_guarded
    def all_users(self) -> list[User]:
        cursor = self._users.find({}, session=self._session).sort("_id", ASCENDING)
        return [_user_from(doc) for doc in cursor]

    @_guarded
    def search_users(self, query: str, limit: int = 10) -> list[User]:
        """See BankStore.search_users. Same contract, done by the database.

        The query is escaped before it becomes a regex. Without that, a user
        typing "a.*" or "(" is writing the pattern themselves - at best a
        confusing result, at worst a pattern that takes the database a very long
        time to evaluate.
        """
        needle = (query or "").strip()
        if not needle:
            return []
        pattern = {"$regex": re.escape(needle), "$options": "i"}
        cursor = self._users.find(
            {"$or": [{"name": pattern}, {"email": pattern}]},
            session=self._session,
        ).sort("_id", ASCENDING).limit(limit)
        return [_user_from(doc) for doc in cursor]

    @_guarded
    def update_user(self, user_id: int, name: str | None = None,
                    email: str | None = None) -> User:
        """Change a user's name, email, or both. See BankStore.update_user for
        why role and password_hash are not reachable from here."""
        changes = {}
        if name is not None:
            changes["name"] = name.strip()
        if email is not None:
            key = email.strip().lower()
            clash = self._users.find_one({"email": key, "_id": {"$ne": user_id}},
                                         {"_id": 1}, session=self._session)
            if clash is not None:
                raise EmailAlreadyUsed(f"email already registered: {key}")
            changes["email"] = key
        if not changes:
            return self.get_user(user_id)
        try:
            doc = self._users.find_one_and_update(
                {"_id": user_id}, {"$set": changes},
                return_document=ReturnDocument.AFTER, session=self._session)
        except DuplicateKeyError:
            # Two edits raced past the check above. The unique index settles it,
            # exactly as it does in add_user.
            raise EmailAlreadyUsed(
                f"email already registered: {changes['email']}") from None
        if doc is None:
            raise UserNotFound(f"no user with id {user_id}")
        return _user_from(doc)

    # ---- accounts ----

    @_guarded
    def add_account(self, account: Account) -> Account:
        if account.account_id is None:
            account.account_id = self._next_id("accounts")
        self._accounts.insert_one({
            "_id": account.account_id, "user_id": account.user_id,
            "account_type": account.account_type, "balance": account.balance,
            "status": account.status, "created_at": account.created_at,
        }, session=self._session)
        return account

    @_guarded
    def get_account(self, account_id: int) -> Account:
        doc = self._accounts.find_one({"_id": account_id}, session=self._session)
        if doc is None:
            raise AccountNotFound(f"no account with id {account_id}")
        return _account_from(doc)

    @_guarded
    def accounts_for_user(self, user_id: int) -> list[Account]:
        cursor = self._accounts.find({"user_id": user_id},
                                     session=self._session).sort("_id", ASCENDING)
        return [_account_from(doc) for doc in cursor]

    @_guarded
    def all_accounts(self) -> list[Account]:
        cursor = self._accounts.find({}, session=self._session).sort("_id", ASCENDING)
        return [_account_from(doc) for doc in cursor]

    @_guarded
    def save_balance(self, account: Account) -> None:
        """Write back a balance changed by Account._apply.

        Inside atomic(), MongoDB rejects this write if another transaction changed
        the same account after this one read it, which surfaces as ConcurrentUpdate.
        """
        result = self._accounts.update_one(
            {"_id": account.account_id}, {"$set": {"balance": account.balance}},
            session=self._session)
        if result.matched_count == 0:
            raise AccountNotFound(f"no account with id {account.account_id}")

    @_guarded
    def save_status(self, account: Account) -> None:
        result = self._accounts.update_one(
            {"_id": account.account_id}, {"$set": {"status": account.status}},
            session=self._session)
        if result.matched_count == 0:
            raise AccountNotFound(f"no account with id {account.account_id}")

    # ---- transactions ----

    @_guarded
    def next_txn_id(self) -> int:
        return self._next_id("transactions")

    @_guarded
    def client_txn_id_seen(self, client_txn_id: str | None) -> bool:
        if client_txn_id is None:
            return False
        return self._transactions.find_one(
            {"client_txn_id": client_txn_id}, {"_id": 1},
            session=self._session) is not None

    @_guarded
    def add_transaction(self, txn: Transaction) -> Transaction:
        doc = {
            "_id": txn.txn_id, "account_id": txn.account_id,
            "txn_type": txn.txn_type, "amount": txn.amount,
            "client_txn_id": txn.client_txn_id, "created_at": txn.created_at,
        }
        if txn.adjusted_by is not None:
            doc["adjusted_by"] = txn.adjusted_by
            doc["reason"] = txn.reason
        try:
            self._transactions.insert_one(doc, session=self._session)
        except DuplicateKeyError as exc:
            if "client_txn_id" in (exc.details or {}).get("keyPattern", {}):
                raise DuplicateTransaction(
                    f"transaction {txn.client_txn_id} has already been submitted"
                ) from None
            raise
        return txn

    @_guarded
    def transactions_for_account(self, account_id: int,
                                 txn_type: str | None = None) -> list[Transaction]:
        query = {"account_id": account_id}
        if txn_type:
            query["txn_type"] = txn_type
        cursor = self._transactions.find(query, session=self._session).sort(
            "_id", DESCENDING)
        return [_transaction_from(doc) for doc in cursor]

    @_guarded
    def ledger_sum(self, account_id: int) -> int:
        """Money in minus money out for one account, in cents, summed by the database."""
        pipeline = [
            {"$match": {"account_id": account_id}},
            {"$group": {"_id": None, "total": {"$sum": {"$cond": [
                {"$in": ["$txn_type", sorted(CREDIT_TYPES)]},
                "$amount",
                {"$multiply": ["$amount", -1]},
            ]}}}},
        ]
        result = list(self._transactions.aggregate(pipeline, session=self._session))
        return int(result[0]["total"]) if result else 0

    @_guarded
    def ledger_sums(self) -> dict[int, int]:
        """See BankStore.ledger_sums. One aggregation for the whole ledger.

        The per-account version is correct and was being called in a loop, which
        made reconciliation cost one round trip per account - about 2.8 seconds
        for 37 of them, and growing with every account opened. Grouping by
        account_id instead asks the same question once.
        """
        pipeline = [
            {"$group": {"_id": "$account_id", "total": {"$sum": {"$cond": [
                {"$in": ["$txn_type", sorted(CREDIT_TYPES)]},
                "$amount",
                {"$multiply": ["$amount", -1]},
            ]}}}},
        ]
        return {int(doc["_id"]): int(doc["total"])
                for doc in self._transactions.aggregate(pipeline, session=self._session)}

    # ---- audit log ----

    @_guarded
    def add_audit_entry(self, actor_user_id: int, action: str,
                        account_id: int | None, reason: str) -> None:
        self._audit.insert_one({
            "_id": self._next_id("audit_log"), "actor_user_id": actor_user_id,
            "action": action, "account_id": account_id, "reason": reason,
            "created_at": datetime.now(timezone.utc),
        }, session=self._session)

    @_guarded
    def audit_entries(self) -> list[tuple]:
        """Oldest first, in the same tuple shape as the in-memory store."""
        cursor = self._audit.find({}, session=self._session).sort("_id", ASCENDING)
        return [(doc["actor_user_id"], doc["action"], doc["account_id"], doc["reason"],
                 doc["created_at"]) for doc in cursor]
