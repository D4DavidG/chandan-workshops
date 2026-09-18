"""Tests for the bank core. Standard library only.

    python3 -m unittest -v

No pytest, no database, no server. Every test is a function call, which is the
payoff for keeping the rules in services.py free of framework imports.
"""
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import FrozenInstanceError

from bank import (
    AccountNotActive, AccountNotFound, BankService, BankStore,
    DuplicateTransaction, InsufficientFunds, InvalidAmount, NotAuthorized,
    SavingsAccount, format_money, parse_amount, to_cents,
)

# Every amount in this file is in cents. Where a figure is not obvious at a
# glance the dollar value is in a trailing comment.


class BankTestCase(unittest.TestCase):
    """Shared fixture: two customers, one admin, three accounts."""

    def setUp(self):
        self.store = BankStore()
        self.svc = BankService(self.store)
        self.aaron = self.svc.register_user("Aaron Forrester", "aaron.forrester@example.com")
        self.erik = self.svc.register_user("Erik Mayes", "erik.mayes@example.com")
        self.david = self.svc.register_user("David Gusmao", "david.gusmao@example.com",
                                            role="ADMIN")
        self.a_checking = self.svc.open_account(self.aaron, "CHECKING", 1250)     # 12.50
        self.a_savings = self.svc.open_account(self.aaron, "SAVINGS", 50000)      # 500.00
        self.e_checking = self.svc.open_account(self.erik, "CHECKING", 8421075)   # 84,210.75

    def tearDown(self):
        """Every test ends with the ledger reconciling. If a rule ever changes a
        balance without writing an entry, whichever test exercised it fails here
        rather than silently passing."""
        self.assertEqual(self.svc.reconcile_all(), [],
                         "balance and ledger disagree after this test")


# --------------------------------------------------------------- money handling

class TestMoney(unittest.TestCase):
    def test_float_is_rejected_not_rounded(self):
        """A float has already lost precision by the time it arrives, so it is
        refused rather than converted."""
        with self.assertRaises(TypeError):
            to_cents(12.50)
        with self.assertRaises(InvalidAmount):
            parse_amount(12.50)

    def test_a_bool_is_not_worth_one_cent(self):
        """`bool` is a subclass of `int` in Python, so `True == 1`. Without an
        explicit check, `{"amount": true}` would be accepted as a one-cent
        deposit instead of refused as nonsense."""
        with self.assertRaises(TypeError):
            to_cents(True)
        with self.assertRaises(InvalidAmount):
            parse_amount(True)

    def test_bad_amounts_are_rejected(self):
        """Zero, negatives, and anything that is not a plain int.

        The strings are here because they are what the old dollars-and-cents API
        accepted. A client that was not updated sends "25.00" and must be told
        no, rather than have it silently coerced - "25.00" as cents would be a
        hundredth of what the caller meant.
        """
        bad = [0, -1, -500,                      # not positive
               "25.00", "2500", "abc", "", " ",  # strings of any shape
               12.50, 0.01, 2500.0,              # floats, even whole ones
               None, True, False, [2500]]
        for amount in bad:
            with self.subTest(amount=amount):
                with self.assertRaises(InvalidAmount):
                    parse_amount(amount)

    def test_good_amounts_are_accepted(self):
        self.assertEqual(parse_amount(1), 1)                  # one cent
        self.assertEqual(parse_amount(123456), 123456)        # 1,234.56
        self.assertEqual(parse_amount(100_000_000), 100_000_000)  # the ceiling

    def test_the_per_transaction_ceiling_is_enforced(self):
        with self.assertRaises(InvalidAmount):
            parse_amount(100_000_001)

    def test_display_formatting(self):
        self.assertEqual(format_money(8421075), "84,210.75")
        self.assertEqual(format_money(1), "0.01")
        self.assertEqual(format_money(0), "0.00")
        # divmod on a negative rounds towards minus infinity, so -12345 would
        # print as -124.55 if the sign were not taken off first.
        self.assertEqual(format_money(-12345), "-123.45")


# -------------------------------------------------------------- business rules

class TestDeposit(BankTestCase):
    def test_deposit_increases_balance_and_writes_one_entry(self):
        before = len(self.store.transactions_for_account(self.a_checking.account_id))
        self.svc.deposit(self.a_checking.account_id, 10000, self.aaron)
        self.assertEqual(self.a_checking.balance, 11250)
        after = len(self.store.transactions_for_account(self.a_checking.account_id))
        self.assertEqual(after - before, 1)

    def test_deposit_must_be_positive(self):
        with self.assertRaises(InvalidAmount):
            self.svc.deposit(self.a_checking.account_id, -1000, self.aaron)
        self.assertEqual(self.a_checking.balance, 1250)

    def test_precision_survives_a_sequence_of_deposits(self):
        acct = self.svc.open_account(self.aaron, "CHECKING")
        for amount in [100010, 23420, 30]:
            self.svc.deposit(acct.account_id, amount, self.aaron)
        self.svc.withdraw(acct.account_id, 4, self.aaron)
        self.assertEqual(acct.balance, 123456)


class TestWithdraw(BankTestCase):
    def test_cannot_withdraw_more_than_balance(self):
        with self.assertRaises(InsufficientFunds):
            self.svc.withdraw(self.a_checking.account_id, 1251, self.aaron)
        self.assertEqual(self.a_checking.balance, 1250)

    def test_withdrawing_the_exact_balance_succeeds(self):
        self.svc.withdraw(self.a_checking.account_id, 1250, self.aaron)
        self.assertEqual(self.a_checking.balance, 0)

    def test_a_failed_withdrawal_writes_no_ledger_entry(self):
        before = len(self.store.transactions_for_account(self.a_checking.account_id))
        with self.assertRaises(InsufficientFunds):
            self.svc.withdraw(self.a_checking.account_id, 99900, self.aaron)
        after = len(self.store.transactions_for_account(self.a_checking.account_id))
        self.assertEqual(before, after)

    def test_savings_minimum_balance_is_enforced_polymorphically(self):
        """A savings account may be drawn down to its minimum and no further.

        Every number here is derived from `SavingsAccount.MINIMUM` rather than
        written out, so this test states the rule instead of one instance of it.
        The minimum is 0 today, which makes the withdrawable amount the whole
        balance; when it was 2500 the same three assertions held. The service
        layer never checks the account type to work any of this out.
        """
        balance = self.a_savings.balance
        available = balance - SavingsAccount.MINIMUM
        self.assertEqual(self.a_savings.available_for_withdrawal(), available)

        with self.assertRaises(InsufficientFunds):
            self.svc.withdraw(self.a_savings.account_id, available + 1, self.aaron)
        self.svc.withdraw(self.a_savings.account_id, available, self.aaron)
        self.assertEqual(self.a_savings.balance, SavingsAccount.MINIMUM)

    def test_checking_has_no_minimum(self):
        self.assertEqual(self.a_checking.available_for_withdrawal(), 1250)


class TestFrozenAccounts(BankTestCase):
    def test_frozen_account_rejects_customer_movement(self):
        self.svc.set_frozen(self.e_checking.account_id, True,
                            "Suspected card compromise reported 2026-09-15", self.david)
        with self.assertRaises(AccountNotActive):
            self.svc.deposit(self.e_checking.account_id, 1000, self.erik)
        with self.assertRaises(AccountNotActive):
            self.svc.withdraw(self.e_checking.account_id, 1000, self.erik)

    def test_unfreezing_restores_movement(self):
        acct_id = self.e_checking.account_id
        self.svc.set_frozen(acct_id, True, "Suspected card compromise, pending review", self.david)
        self.svc.set_frozen(acct_id, False, "Review complete, no fraud found", self.david)
        self.svc.deposit(acct_id, 1000, self.erik)
        self.assertEqual(self.e_checking.balance, 8422075)


class TestIdempotency(BankTestCase):
    def test_transaction_is_immutable(self):
        txn = self.svc.deposit(self.a_checking.account_id, 1000, self.aaron, "txn-immutable")
        with self.assertRaises(FrozenInstanceError):
            txn.amount = 999

    def test_the_same_submission_is_not_applied_twice(self):
        body = (10000, self.aaron, "submit-attempt-0001")
        self.svc.deposit(self.a_checking.account_id, *body)
        with self.assertRaises(DuplicateTransaction):
            self.svc.deposit(self.a_checking.account_id, *body)
        self.assertEqual(self.a_checking.balance, 11250)

    def test_different_ids_both_apply(self):
        self.svc.deposit(self.a_checking.account_id, 1000, self.aaron, "a")
        self.svc.deposit(self.a_checking.account_id, 1000, self.aaron, "b")
        self.assertEqual(self.a_checking.balance, 3250)


# --------------------------------------------------------------- authorization

class TestOwnership(BankTestCase):
    def test_a_user_cannot_read_another_users_account(self):
        """The vulnerability in the brief as written."""
        with self.assertRaises(AccountNotFound):
            self.svc.get_account_for(self.e_checking.account_id, self.aaron)

    def test_the_error_does_not_reveal_that_the_account_exists(self):
        """Same exception type and message for 'not yours' and 'does not exist'."""
        try:
            self.svc.get_account_for(self.e_checking.account_id, self.aaron)
        except AccountNotFound as exc:
            not_mine = str(exc)
        try:
            self.svc.get_account_for(99999, self.aaron)
        except AccountNotFound as exc:
            missing = str(exc)
        self.assertEqual(
            not_mine.replace(str(self.e_checking.account_id), "X"),
            missing.replace("99999", "X"),
        )

    def test_a_user_cannot_move_another_users_money(self):
        with self.assertRaises(AccountNotFound):
            self.svc.withdraw(self.e_checking.account_id, 100, self.aaron)
        with self.assertRaises(AccountNotFound):
            self.svc.deposit(self.e_checking.account_id, 100, self.aaron)
        self.assertEqual(self.e_checking.balance, 8421075)

    def test_a_user_cannot_read_another_users_history(self):
        with self.assertRaises(AccountNotFound):
            self.svc.history(self.e_checking.account_id, self.aaron)

    def test_admin_may_read_any_account(self):
        acct = self.svc.get_account_for(self.e_checking.account_id, self.david)
        self.assertEqual(acct.balance, 8421075)


class TestAdmin(BankTestCase):
    def test_customers_are_locked_out_of_admin_actions(self):
        for call in (
            lambda: self.svc.all_users(self.aaron),
            lambda: self.svc.all_accounts(self.aaron),
            lambda: self.svc.set_frozen(self.a_checking.account_id, True,
                                        "trying to freeze my own account", self.aaron),
            lambda: self.svc.adjust(self.a_checking.account_id, 100000, "CREDIT",
                                    "giving myself a thousand dollars", self.aaron),
        ):
            with self.subTest(call=call):
                with self.assertRaises(NotAuthorized):
                    call()

    def test_adjustment_writes_a_ledger_entry_and_an_audit_row(self):
        self.svc.adjust(self.a_checking.account_id, 5000, "CREDIT",
                        "Reversing a fee misposted on 2026-09-10", self.david)
        self.assertEqual(self.a_checking.balance, 6250)
        self.assertEqual(len(self.svc.audit), 1)
        actor, action, account_id, reason, created_at = self.svc.audit[0]
        self.assertEqual(actor, self.david.user_id)
        self.assertEqual(action, "ADJUST_CREDIT")
        self.assertIn("misposted", reason)
        self.assertEqual(account_id, self.a_checking.account_id)
        # Timezone-aware and recorded now. A naive datetime here would be read as
        # local time by a client and shift the whole log by the UTC offset.
        self.assertIsNotNone(created_at.tzinfo)
        self.assertLess(datetime.now(timezone.utc) - created_at, timedelta(seconds=30))

    def test_a_credit_account_can_be_read_back(self):
        """A type the factory does not know makes every read of the account list
        raise, which takes out a whole page rather than one row. CREDIT is in the
        shared database already, so the factory has to know it."""
        from bank.models import make_account
        account = make_account("CREDIT", user_id=self.aaron.user_id)
        self.assertEqual(account.account_type, "CREDIT")

    def test_a_credit_account_still_cannot_go_negative_yet(self):
        """Pinning the limitation rather than leaving it implied: this is not a
        real credit account until Account._apply takes its floor from
        minimum_balance. See CreditAccount's docstring."""
        from bank.models import make_account
        account = make_account("CREDIT", user_id=self.aaron.user_id)
        self.assertEqual(account.minimum_balance, 0)
        with self.assertRaises(InsufficientFunds):
            account._apply(-100)

    def test_adjustment_requires_a_written_reason(self):
        with self.assertRaises(ValueError):
            self.svc.adjust(self.a_checking.account_id, 5000, "CREDIT", "oops", self.david)

    def test_adjustment_cannot_take_a_balance_negative(self):
        with self.assertRaises(InsufficientFunds):
            self.svc.adjust(self.a_checking.account_id, 50000, "DEBIT",
                            "Attempting to claw back more than is present", self.david)
        self.assertEqual(self.a_checking.balance, 1250)

    def test_there_is_no_way_for_an_admin_to_set_a_balance_directly(self):
        """If someone adds a set_balance method, this test should fail and the
        review conversation should happen."""
        self.assertFalse(hasattr(self.svc, "set_balance"))
        self.assertFalse(hasattr(self.a_checking, "set_balance"))

    def test_balance_has_no_public_setter(self):
        with self.assertRaises(AttributeError):
            self.a_checking.balance = 100000000


# -------------------------------------------------------------------- transfer

class TestTransfer(BankTestCase):
    def test_transfer_moves_money_and_writes_both_legs(self):
        self.svc.transfer(self.a_savings.account_id, self.e_checking.account_id,
                          10000, self.aaron)
        self.assertEqual(self.a_savings.balance, 40000)
        self.assertEqual(self.e_checking.balance, 8431075)

    def test_cannot_transfer_from_an_account_you_do_not_own(self):
        with self.assertRaises(AccountNotFound):
            self.svc.transfer(self.e_checking.account_id, self.a_checking.account_id,
                              10000, self.aaron)

    def test_a_failed_transfer_moves_nothing(self):
        with self.assertRaises(InsufficientFunds):
            self.svc.transfer(self.a_checking.account_id, self.e_checking.account_id,
                              999900, self.aaron)
        self.assertEqual(self.a_checking.balance, 1250)
        self.assertEqual(self.e_checking.balance, 8421075)


# ------------------------------------------------------------------ invariants

class TestInvariants(BankTestCase):
    def test_opening_balance_gets_a_ledger_entry(self):
        """An account given a balance with no entry behind it breaks reconciliation
        from the moment it exists."""
        stored, ledger = self.svc.reconcile(self.a_checking.account_id)
        self.assertEqual(stored, ledger)
        self.assertEqual(stored, 1250)

    def test_reconciliation_holds_across_a_long_sequence(self):
        acct = self.a_savings.account_id
        for amount in [1001, 9999, 1, 123456]:
            self.svc.deposit(acct, amount, self.aaron)
        for amount in [555, 1, 10000]:
            self.svc.withdraw(acct, amount, self.aaron)
        stored, ledger = self.svc.reconcile(acct)
        self.assertEqual(stored, ledger)

    def test_history_is_paginated(self):
        acct = self.a_savings.account_id
        for _ in range(25):
            self.svc.deposit(acct, 100, self.aaron)
        rows, total = self.svc.history(acct, self.aaron, page=1, page_size=10)
        self.assertEqual(len(rows), 10)
        self.assertEqual(total, 26)  # 25 deposits plus the opening entry
        rows, _ = self.svc.history(acct, self.aaron, page=3, page_size=10)
        self.assertEqual(len(rows), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestCreditAccountType(unittest.TestCase):
    """The third account type. Behaves like checking today - see CreditAccount."""

    def setUp(self):
        self.svc = BankService(BankStore())
        self.user = self.svc.register_user("Cred Holder", "cred@example.com",
                                           password="Pw123456!")

    def test_can_be_opened(self):
        account = self.svc.open_account(self.user, "CREDIT", 5000)
        self.assertEqual(account.account_type, "CREDIT")
        self.assertEqual(account.balance, 5000)

    def test_lowercase_is_accepted_like_the_others(self):
        self.assertEqual(self.svc.open_account(self.user, "credit").account_type,
                         "CREDIT")

    def test_an_unknown_type_is_still_refused(self):
        with self.assertRaises(ValueError):
            self.svc.open_account(self.user, "MORTGAGE")

    def test_it_cannot_go_negative_yet(self):
        """The documented limit of this type: it is not a real credit line. If
        this test ever starts failing, CreditAccount grew a credit limit and the
        docstring needs to stop saying it has not."""
        account = self.svc.open_account(self.user, "CREDIT", 1000)
        with self.assertRaises(InsufficientFunds):
            self.svc.withdraw(account.account_id, 1001, self.user)
