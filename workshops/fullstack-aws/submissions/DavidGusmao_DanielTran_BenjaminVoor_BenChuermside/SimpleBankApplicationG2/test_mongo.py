"""Integration tests against a real MongoDB database. Opt in; they need Atlas.

    PowerShell:  $env:MONGO_TESTS = "1"; python -m unittest test_mongo -v
    bash:        MONGO_TESTS=1 python -m unittest test_mongo -v

Skipped otherwise, so the normal `python -m unittest` stays fast and works
without a network connection.

They always use the database `simple_bank_test`, whatever MONGODB_DB says, and
they wipe it before every test. Never point them anywhere else.

`test_bank.py` and `test_api.py` prove the rules with the in-memory store. These
prove that MongoStore keeps the same promises once the data lives in a database:
that it is really saved, that the unique indexes refuse duplicates, and that two
separate connections cannot spend the same money.

`MongoConnectionTest` below is a plain sanity check against the Atlas cluster
itself (can we connect at all, is the sample dataset there) before the heavier
`MongoStoreTest` suite runs.
"""
import os
import threading
import unittest

from bank.config import load_env

load_env()
TEST_DB = "simple_bank_test"
ENABLED = os.environ.get("MONGO_TESTS") == "1" and bool(os.environ.get("MONGODB_URI"))

if ENABLED:
    import json

    from pymongo import MongoClient

    from bank import BankAPI, BankService
    from bank.errors import (
        AccountNotActive, ConcurrentUpdate, DuplicateTransaction, EmailAlreadyUsed,
        InsufficientFunds,
    )
    from bank.mongo_store import MongoStore
    from bank.security import hash_password, issue_token

    HASH = hash_password("Password123!", rounds=1_000)


@unittest.skipUnless(ENABLED, "set MONGO_TESTS=1, with MONGODB_URI in .env, to run")
class MongoConnectionTest(unittest.TestCase):
    """Can we even reach the cluster, before we ask MongoStore to do anything with it."""

    @classmethod
    def setUpClass(cls):
        cls.client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=10_000)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_connection_is_available(self):
        self.assertEqual(self.client.admin.command("ping")["ok"], 1.0)

    def test_sample_analytics_accounts_are_available(self):
        account = self.client.sample_analytics.accounts.find_one({"account_id": 371138})
        self.assertIsNotNone(account)
        self.assertEqual(account["account_id"], 371138)


@unittest.skipUnless(ENABLED, "set MONGO_TESTS=1, with MONGODB_URI in .env, to run")
class MongoStoreTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        uri = os.environ["MONGODB_URI"]
        cls.store = MongoStore(uri, TEST_DB)
        # A second store with its own connection. Reading through it proves the
        # data is in the database rather than cached on a Python object, and
        # using both at once stands in for two separate server processes.
        cls.other = MongoStore(uri, TEST_DB)
        assert cls.store.db_name == cls.other.db_name == TEST_DB

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.other.close()

    def setUp(self):
        self.store.reset()
        self.svc = BankService(self.store)
        self.alice = self.svc.register_user("Alice Test", "alice@example.com",
                                            password_hash=HASH)
        self.bob = self.svc.register_user("Bob Test", "bob@example.com",
                                          password_hash=HASH)
        self.admin = self.svc.register_user("Admin Test", "admin@example.com",
                                            role="ADMIN", password_hash=HASH)
        self.a1 = self.svc.open_account(self.alice, "CHECKING", 10_000)
        self.b1 = self.svc.open_account(self.bob, "CHECKING", 5_000)

    def tearDown(self):
        self.assertEqual(self.svc.reconcile_all(), [],
                         "a balance and its ledger disagree in the database")

    def balance(self, account_id):
        return self.other.get_account(account_id).balance

    # ---- storage ----

    def test_ids_are_sequential_integers(self):
        self.assertEqual([self.alice.user_id, self.bob.user_id, self.admin.user_id],
                         [1, 2, 3])
        self.assertEqual([self.a1.account_id, self.b1.account_id], [1, 2])

    def test_records_are_really_in_the_database(self):
        self.assertEqual(self.balance(self.a1.account_id), 10_000)
        self.assertEqual(self.other.find_user_by_email("ALICE@example.com").user_id,
                         self.alice.user_id)
        self.assertIsInstance(self.balance(self.a1.account_id), int)

    def test_deposit_and_withdraw_are_saved(self):
        self.svc.deposit(self.a1.account_id, 2_500, self.alice)
        self.svc.withdraw(self.a1.account_id, 1_000, self.alice)
        self.assertEqual(self.balance(self.a1.account_id), 11_500)
        types = [t.txn_type for t in self.other.transactions_for_account(self.a1.account_id)]
        self.assertEqual(types, ["WITHDRAWAL", "DEPOSIT", "DEPOSIT"])
        self.assertEqual(self.other.ledger_sum(self.a1.account_id), 11_500)

    # ---- rules the database now enforces ----

    def test_an_overdraft_changes_nothing(self):
        with self.assertRaises(InsufficientFunds):
            self.svc.withdraw(self.a1.account_id, 10_001, self.alice)
        self.assertEqual(self.balance(self.a1.account_id), 10_000)
        self.assertEqual(len(self.other.transactions_for_account(self.a1.account_id)), 1)

    def test_the_unique_index_refuses_a_duplicate_email(self):
        with self.assertRaises(EmailAlreadyUsed):
            self.svc.register_user("Impostor", "ALICE@example.com", password_hash=HASH)

    def test_a_repeated_submission_is_applied_once(self):
        self.svc.deposit(self.a1.account_id, 500, self.alice, client_txn_id="click-1")
        with self.assertRaises(DuplicateTransaction):
            self.svc.deposit(self.a1.account_id, 500, self.alice, client_txn_id="click-1")
        self.assertEqual(self.balance(self.a1.account_id), 10_500)

    def test_a_transfer_saves_both_legs(self):
        self.svc.transfer(self.a1.account_id, self.b1.account_id, 3_000, self.alice)
        self.assertEqual(self.balance(self.a1.account_id), 7_000)
        self.assertEqual(self.balance(self.b1.account_id), 8_000)

    def test_a_refused_transfer_leaves_both_accounts_alone(self):
        self.svc.set_frozen(self.b1.account_id, True, "Frozen for the transfer test",
                            self.admin)
        with self.assertRaises(AccountNotActive):
            self.svc.transfer(self.a1.account_id, self.b1.account_id, 3_000, self.alice)
        self.assertEqual(self.balance(self.a1.account_id), 10_000)
        self.assertEqual(self.balance(self.b1.account_id), 5_000)

    def test_a_freeze_is_saved(self):
        self.svc.set_frozen(self.b1.account_id, True, "Suspected compromise, test",
                            self.admin)
        self.assertEqual(self.other.get_account(self.b1.account_id).status, "FROZEN")
        with self.assertRaises(AccountNotActive):
            self.svc.deposit(self.b1.account_id, 100, self.bob)

    def test_adjustments_and_the_audit_log_are_saved(self):
        txn = self.svc.adjust(self.a1.account_id, 1_500, "CREDIT",
                              "Reversing a misposted fee, test", self.admin)
        stored = self.other.transactions_for_account(self.a1.account_id)[0]
        self.assertEqual(stored.txn_id, txn.txn_id)
        self.assertEqual(stored.adjusted_by, self.admin.user_id)
        entries = self.other.audit_entries()
        self.assertEqual(entries[-1][1], "ADJUST_CREDIT")
        self.assertIn("misposted", entries[-1][3])

    # ---- through the API ----

    def test_a_token_signed_here_works_against_the_other_connection(self):
        """Nothing about a session is stored, so a token issued against one
        connection authenticates against another with no shared state beyond the
        signing key. That is the stateless property, and it is what would let
        two server processes sit behind a load balancer."""
        token = issue_token(self.alice.user_id, self.alice.email,
                            self.alice.role, "mongo-test-secret")
        other_api = BankAPI(BankService(self.other), secret="mongo-test-secret")
        status, body = other_api.handle("GET", "/api/auth/me", b"",
                                        {"authorization": f"Bearer {token}"})
        self.assertEqual(status, 200)
        self.assertEqual(body["user"]["email"], self.alice.email)

    def test_the_tokens_collection_does_not_exist(self):
        """Sessions are signed, not stored. If this fails, something started
        writing session state to the database again."""
        self.assertNotIn("tokens", self.store._db.list_collection_names())

    def test_a_deposit_over_the_api_is_saved(self):
        api = BankAPI(self.svc, secret="mongo-test-secret")
        token = issue_token(self.alice.user_id, self.alice.email,
                            self.alice.role, "mongo-test-secret")
        status, body = api.handle(
            "POST", f"/api/accounts/{self.a1.account_id}/deposit",
            json.dumps({"amount": 100}).encode(), {"authorization": f"Bearer {token}"})
        self.assertEqual(status, 201)
        self.assertEqual(body["account"]["balance"], 10_100)
        self.assertEqual(self.balance(self.a1.account_id), 10_100)

    # ---- concurrency ----

    def test_two_connections_cannot_spend_the_same_money(self):
        """Eight withdrawals of 30.00 against 100.00, split across two stores.

        Each store has its own connection and its own lock, like two server
        processes. Only the database transaction stands between them, so this
        is the test of it. At most three withdrawals fit, and every refusal must
        be a clean domain error rather than a half-applied change.
        """
        services = [BankService(self.store), BankService(self.other)]
        outcomes, guard = [], threading.Lock()

        def attempt(svc):
            try:
                svc.withdraw(self.a1.account_id, 3_000, self.alice)
                result = "ok"
            except (InsufficientFunds, ConcurrentUpdate) as exc:
                result = type(exc).__name__
            with guard:
                outcomes.append(result)

        threads = [threading.Thread(target=attempt, args=(services[i % 2],))
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        succeeded = outcomes.count("ok")
        self.assertEqual(len(outcomes), 8)
        self.assertLessEqual(succeeded, 3)
        self.assertEqual(self.balance(self.a1.account_id), 10_000 - 3_000 * succeeded)


if __name__ == "__main__":
    unittest.main(verbosity=2)
