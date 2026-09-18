"""Money handling. Read this file first.

Rule: money is an `int` number of cents. Never a float, never a Decimal, never a
string. A balance of 1,234.56 is stored, summed, compared and sent over the wire
as `123456`.

WHY NOT FLOAT
-------------
A float cannot represent 0.10 exactly, so sums drift:

    >>> 1000.10 + 234.20 + 0.30 - 0.04
    1234.5599999999999

In a system that moves money that difference is not cosmetic, and it compounds
across a ledger. This was question 10 on the Day 1 module assessment
(BigDecimal / Decimal for high-precision financial calculations).

WHY NOT DECIMAL EITHER
----------------------
`Decimal` is the other correct answer to that question, and this module used to
be built on it. Integer cents is the same answer taken one step further, and it
wins on four counts:

  1. **There is no fractional cent to round.** `Decimal` is exact, but exactness
     only holds if every value is quantized to two places on the way in - forget
     one `.quantize()` and `1.005` survives to be rounded inconsistently later.
     An `int` cannot hold a third decimal place, so the rule is enforced by the
     type rather than by remembering to call something.

  2. **`==` is trustworthy.** Reconciliation asks whether a stored balance equals
     the sum of a ledger. On integers that comparison has no caveats at all.

  3. **It crosses JSON intact.** `Decimal` is not JSON-serializable, so it had to
     go out as a quoted string `"1234.56"` and be parsed back by every client. A
     JSON integer is exact to 2^53 - about 90 trillion dollars in cents - so the
     number the server holds is the number the browser receives.

  4. **It maps to one database column.** `BIGINT`, rather than a `DECIMAL(19,4)`
     whose precision every driver reports differently.

The cost is that a raw amount is no longer human-readable: `123456` has to be
divided by 100 before anyone sees it. That conversion happens in exactly two
places - `format_money` for display, and the frontend for rendering - and never
in the middle of a calculation.
"""

# Every amount below is in cents.
MAX_TXN_AMOUNT = 100_000_000  # 1,000,000.00 per transaction


def to_cents(value) -> int:
    """Accept a value that is already a whole number of cents, or refuse it.

    This is deliberately not a converter. There is nothing to convert to: if a
    value is not an `int`, it did not come from this system's money type, and
    guessing what it meant is how a 25-dollar amount becomes a 25-cent one.

    `bool` is rejected explicitly because `bool` is a subclass of `int` in
    Python, so `True` would otherwise sail through and be worth one cent.
    """
    if isinstance(value, bool):
        raise TypeError(f"Refusing to treat a bool as money. Got {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise TypeError(
            "Refusing to build money from a float. Money is a whole number of "
            f"cents, so pass an int. Got {value!r}"
        )
    raise TypeError(
        "Money must be an int number of cents, e.g. 2500 for 25.00. "
        f"Got {value!r} ({type(value).__name__})"
    )


def parse_amount(raw) -> int:
    """Validate an amount that came from outside the program.

    "Outside" means an HTTP request body or a console prompt. The rules are the
    same either way, which is why they live here and not in whatever is reading
    the input.

    A JSON body of `{"amount": 2500}` arrives here as the int 2500 and passes.
    `{"amount": 25.00}` arrives as a float and is refused rather than rounded -
    a float is the client saying "dollars" to an API that speaks cents, and the
    two readings differ by a factor of a hundred. Refusing is the only safe
    answer; guessing would be a silent 100x error in either direction.
    """
    from .errors import InvalidAmount

    if isinstance(raw, bool) or not isinstance(raw, int):
        raise InvalidAmount(
            "amount must be a whole number of cents given as a JSON integer, "
            "e.g. 2500 for 25.00"
        )
    if raw <= 0:
        raise InvalidAmount("amount must be greater than zero")
    if raw > MAX_TXN_AMOUNT:
        raise InvalidAmount(
            f"amount exceeds the per-transaction limit of "
            f"{format_money(MAX_TXN_AMOUNT)}"
        )
    return raw


def format_money(cents: int) -> str:
    """Display form with thousands separators: 8421075 -> '84,210.75'.

    Presentation only. Nothing downstream of this function does arithmetic, and
    nothing sends the result over the wire - the API sends the integer.

    Negatives are handled by taking the sign off first. `divmod(-12345, 100)` is
    `(-124, 55)` in Python, which would print as -124.55 rather than -123.45.
    """
    cents = to_cents(cents)
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}{whole:,}.{part:02d}"
